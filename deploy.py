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
		self.local_payload_folder = "/path/to/local/folder/"
		self.delete_after_command_finished = True

	def command(self, payload_folder, gateway, domain, index, total_workers):
		cmd = "chmod +x "+payload_folder+"/anExecutable && ./anExecutable"
		return cmd

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
		self.gateway = None
		pass

	def deploy(self, deployment_listing, target_folder, script_filename, payload_path):
		print "Connecting to worker: " + self.domain
		session = paramiko.SSHClient()
		session.set_missing_host_key_policy(paramiko.AutoAddPolicy())
		session.connect(self.domain, username=settings.username)

		print "Uploading payload"
		self.upload_files(session, deployment_listing, target_folder)

		print "Bootstrapping payload"
		remote_script_path = os.path.join(target_folder, script_filename)
		remote_output_path = os.path.join(target_folder, "output.log")
		cmd = "nohup python '"+remote_script_path+"' -run"
		cmd += " -name "+self.domain
		if self.gateway != None:
			cmd += " -gateway "+self.gateway.domain
		cmd += " -source_dir '"+target_folder+"' -script '"+script_filename+"' -payload_dir '"+payload_path+"' &> '"+remote_output_path+"'"
		(stdin, stdout, stderr) = session.exec_command(cmd)

		print "Closing connection"
		session.close()

	def upload_files(self, session, deployment_listing, target_folder):
		ftp = session.open_sftp()
		print(target_folder)
		ftp.mkdir(target_folder)
		for (localfile, relativepath) in deployment_listing:
			print "   " + relativepath
			ftp_create_folders_for_file(ftp, target_folder, relativepath)
			ftp.put(localfile, os.path.join(target_folder, relativepath))
		ftp.close()


class Gateway:
	def __init__(self, domain, workers):
		self.domain = domain
		self.workers = workers
		for worker in workers:
			worker.gateway = self
		pass

	def deploy(self, deployment_listing, target_folder, script_filename, payload_path):
		# Open SSH session to main server
		print "Connecting to gateway: " + self.domain
		gateway = paramiko.SSHClient()
		gateway.set_missing_host_key_policy(paramiko.AutoAddPolicy())
		gateway.connect(self.domain, username=settings.username, compress=True)

		# Open SSH session to deploy master
		deploy_master_device = self.workers[random.randint(0, len(self.workers)-1)]
		deploy_master_domain = deploy_master_device.domain
		print "Chose " + deploy_master_domain + " as deploy master"
		deploy_master_channel = gateway.get_transport().open_channel('direct-tcpip', (deploy_master_domain, 22), ('127.0.0.1', 0))
		deploy_master = paramiko.SSHClient()
		deploy_master.set_missing_host_key_policy(paramiko.AutoAddPolicy())
		deploy_master.connect(deploy_master_domain, sock=deploy_master_channel, username=settings.username)

		# Forward key agent to deploy master
		deploy_master_agent_session = deploy_master.get_transport().open_session()
		deploy_master_agent_channel = paramiko.agent.AgentRequestHandler(deploy_master_agent_session)

		# Upload files to deploy master
		print "Uploading files to deploy master"
		deploy_master_device.upload_files(deploy_master, deployment_listing, target_folder)

		# Run second stage deployment on deploy master
		print "Running second stage deployment script on deploy master"
		print ""

		remote_script_path = os.path.join(target_folder, script_filename)
		remote_deploy_output_path = os.path.join(target_folder, "deploy_output.log")
		command = "python '"+remote_script_path+"' -as_deploy_master -gateway "+self.domain+" -name "+deploy_master_domain + " -source_dir '"+target_folder+"' -script '"+script_filename+"' -payload_dir '"+payload_path+"' 2>&1 | tee '"+remote_deploy_output_path+"'"
		(stdin, stdout, stderr) = deploy_master.exec_command(command)
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
		
		print ""
		print "Bootstrapping payload on deploy master"
		remote_output_path = os.path.join(target_folder, "output.log")
		command = "nohup python '"+remote_script_path+"' -run -gateway "+self.domain+" -name "+deploy_master_domain + " -source_dir '"+target_folder+"' -script '"+script_filename+"' -payload_dir '"+payload_path+"' &> '"+remote_output_path+"'"
		(stdin, stdout, stderr) = deploy_master.exec_command(command)

		# Cleanup
		#print "Removing deployment files"
		#deploy_master.exec_command("rm -r '"+target_folder+"'")

		print "Closing connection"
		deploy_master.close()
		gateway.close()

settings = Settings()

def deploy():
	# Files
	script_filepath = os.path.realpath(__file__)
	script_filename = os.path.basename(script_filepath)
	remote_dir = "/tmp/deploy" + str(random.randint(1E6, 1E8)) + "/"

	files_to_deploy = [os.path.join(dp, f) for dp, dn, filenames in os.walk(settings.local_payload_folder) for f in filenames]
	deployment_listing = [(p, os.path.join("data", os.path.relpath(p, settings.local_payload_folder))) for p in files_to_deploy]
	deployment_listing.append((script_filepath, script_filename))

	for device in settings.network:
		device.deploy(deployment_listing, remote_dir, script_filename, "data")
	

def deploy_to_workers():
	own_domain = sys.argv[sys.argv.index("-name")+1]
	own_gateway = sys.argv[sys.argv.index("-gateway")+1]
	print "Hello world from "+own_gateway+"|"+own_domain
	source_dir = sys.argv[sys.argv.index("-source_dir")+1]
	payload_dir = sys.argv[sys.argv.index("-payload_dir")+1]
	script_filename = sys.argv[sys.argv.index("-script")+1]

	gateway_dev = None
	for device in settings.network:
		if device.domain == own_gateway:
			gateway_dev = device

	for subdevice in gateway_dev.workers:
		if subdevice.domain == own_domain:
			continue

		files_to_deploy = [os.path.join(dp, f) for dp, dn, filenames in os.walk(source_dir) for f in filenames]
		deployment_listing = [(p, os.path.relpath(p, source_dir)) for p in files_to_deploy]

		subdevice.deploy(deployment_listing, source_dir, script_filename, payload_dir)

def run():
	own_domain = sys.argv[sys.argv.index("-name")+1]
	own_gateway = None
	if "-gateway" in sys.argv:
		own_gateway = sys.argv[sys.argv.index("-gateway")+1]
	source_dir = sys.argv[sys.argv.index("-source_dir")+1]
	payload_dir = sys.argv[sys.argv.index("-payload_dir")+1]
	payload_folder = os.path.join(source_dir, payload_dir)

	i = 0
	i_found = False
	for device in settings.network:
		if i_found:
			break

		if isinstance(device, Gateway):
			if device.domain == own_gateway:
				for subdevice in device.workers:
					if subdevice.domain == own_domain:
						i_found = True
						break
					else:
						i += 1
			else:
				i += len(device.workers)
		else:
			if device.domain == own_domain:
				i_found = True
				break
			else:
				i += 1

	total_workers = 0
	for device in settings.network:
		if isinstance(device, Gateway):
			total_workers += len(device.workers)
		else:
			total_workers += 1

	cmd = settings.command(payload_folder, own_gateway, own_domain, i, total_workers)
	print("Executing command: "+cmd)
	os.system(cmd)

	if settings.delete_after_command_finished:
		os.system("rm -r '"+source_dir+"'")


def rec_split(s):
	rest, tail = os.path.split(s)
	if rest in ('', os.path.sep):
		return tail,
	return rec_split(rest) + (tail,)

def ftp_create_folders_for_file(ftp, root, rel_path):
	ftp_create_folders_from_list(ftp, root, rec_split(rel_path)[:-1])

def ftp_create_folders(ftp, root, rel_path):
	ftp_create_folders_from_list(ftp, root, rec_split(rel_path))

def ftp_create_folders_from_list(ftp, root, rel_path_list):
	curpath = root
	for part in rel_path_list:
		parent = curpath
		curpath = os.path.join(curpath, part)
		if not part in ftp.listdir(parent):
			ftp.mkdir(curpath)

if "-as_deploy_master" in sys.argv:
	deploy_to_workers()
elif "-run" in sys.argv:
	run()
else:
	deploy()