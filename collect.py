#!/usr/bin/python

# Imports

import random
import select
import pip
import sys
import os

#### SETTINGS ####
class Settings:
	def __init__(self):
		self.network = [
			Gateway("gateway.example.com", [
				Worker("worker1.example.com"),
				Worker("worker2.example.com")
			]),
			Worker("worker.other.example.com")
		]
		self.username = "yourSSHusername"
		self.remote_payload_folder = lambda domain, index: "/folder/on/remote/machine"
		self.payload_ready_predicate = lambda domain, index: "test -f /folder/on/remote/machine/some_file"
		self.delete_payload_after_download = True
		self.local_dest_folder = "/folder/on/local/machine"

##################

def install_and_import(package):
    import importlib
    try:
        importlib.import_module(package)
    except ImportError:
        import pip
        pip.main(['install', package])
    finally:
        globals()[package] = importlib.import_module(package)

install_and_import('paramiko')

class Worker:
	def __init__(self, domain):
		self.domain = domain
		pass

	def collect(self, channel=None):
		idx = self.get_index()
		print "Connecting to worker "+str(idx)+": " + self.domain
		session = paramiko.SSHClient()
		session.set_missing_host_key_policy(paramiko.AutoAddPolicy())
		if channel == None:
			session.connect(self.domain, username=settings.username, compress = True)
		else:
			session.connect(self.domain, sock=channel, username=settings.username, compress = True)

		print "Checking payload status"
		(stdin, stdout, stderr) = session.exec_command(settings.payload_ready_predicate(self.domain, idx))
		while not stdout.channel.exit_status_ready():
			# Only print data if there is data to read in the channel
			if stdout.channel.recv_ready():
				rl, wl, xl = select.select([ stdout.channel ], [ ], [ ], 0.0)
				if len(rl) > 0:
					tmp = stdout.channel.recv(1024)
					output = tmp.decode()
					print output
			if stderr.channel.recv_ready():
				rl, wl, xl = select.select([ stderr.channel ], [ ], [ ], 0.0)
				if len(rl) > 0:
					tmp = stderr.channel.recv(1024)
					output = tmp.decode()
					print output
		exitcode = stdout.channel.recv_exit_status()

		if exitcode == 0:
			print "✅ Payload ready, downloading"
			ftp = session.open_sftp()

			local_target_folder = os.path.join(settings.local_dest_folder, str(idx))
			remote_folder = settings.remote_payload_folder(self.domain, idx)
			ftp_download_folder(ftp, remote_folder, local_target_folder, settings.delete_payload_after_download)
			ftp.close()

		else:
			print "Payload not ready yet"

		print "Closing connection"
		
		session.close()

	def get_index(self):
		i = 0
		i_found = False
		for device in settings.network:
			if i_found:
				break

			if isinstance(device, Gateway):
				if device == self.gateway:
					for subdevice in device.workers:
						if subdevice == self:
							i_found = True
							break
						else:
							i += 1
				else:
					i += len(device.workers)
			else:
				if device == self:
					i_found = True
					break
				else:
					i += 1
		return i

class Gateway:
	def __init__(self, domain, workers):
		self.domain = domain
		self.workers = workers
		for worker in workers:
			worker.gateway = self
		pass

	def collect(self):
		# Open SSH session to main server
		print "Connecting to gateway: " + self.domain
		gateway = paramiko.SSHClient()
		gateway.set_missing_host_key_policy(paramiko.AutoAddPolicy())
		gateway.connect(self.domain, username=settings.username, compress=True)
		for worker in self.workers:
			subsession_channel = gateway.get_transport().open_channel('direct-tcpip', (worker.domain, 22), ('127.0.0.1', 0))
			worker.collect(subsession_channel)
		gateway.close()

settings = Settings()

def collect():
	if not os.path.exists(settings.local_dest_folder):
		os.makedirs(settings.local_dest_folder)

	for device in settings.network:
		device.collect()

def ftp_download_folder(ftp, remote_folder, local_folder, delete_after_download):
	if not os.path.exists(local_folder):
		os.makedirs(local_folder)

	files = ftp.listdir(remote_folder)
	for file in files:
		remote_path = os.path.join(remote_folder, file)
		local_path = os.path.join(local_folder, file)
		is_directory = ftp.stat(remote_path).st_mode & 0040000
		if is_directory:
			ftp_download_folder(ftp, remote_path, local_path, delete_after_download)
		else:
			print "   " + remote_path
			ftp.get(remote_path, local_path)
			if delete_after_download:
				ftp.remove(remote_path)
	if delete_after_download:
		ftp.rmdir(remote_folder)

collect()