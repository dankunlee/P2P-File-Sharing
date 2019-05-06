import socket, sys, threading, json,time,os,ssl
import os.path
import glob
import json
import optparse

#Validate the IP address of the correct format
def validate_ip(s):
    '''
    Arguments:
    s -- dot decimal IP address in string
    Returns:
    True if valid; False otherwise
    '''
    a = s.split('.')
    if len(a) != 4:
        return False
    for x in a:
        if not x.isdigit():
            return False
        i = int(x)
        if i < 0 or i > 255:
            return False
    return True

# Validate the port number is in range [0,2^16 -1 ]
def validate_port(x):
    '''
    Arguments:
    x -- port number
    Returns:
    True if valid; False, otherwise
    '''
    if not x.isdigit():
        return False
    i = int(x)
    if i < 0 or i > 65535:
            return False
    return True

# Get file info in the local directory (subdirectories are ignored)
# Note: Exclude files with .so, .py, .dll suffixes
def get_file_info():
    '''
    Get file information in the current folder. which is used to construct the
    intial message as the instructions (exclude subfolder, you may also exclude *.py)

    Return: an array, with each element is {'name':filename,'mtime':mtime}
    i.e, [{'name':filename,'mtime':mtime},{'name':filename,'mtime':mtime},...]

    '''
    fileInfo = []
    fileList = os.listdir() #get files/subfolders in current directory 
    for file in fileList:
        if '.py' in file or not os.path.isfile(file) :    #exclude *.py or subfolders 
            # fileList.remove(file)
            continue
        mtime = int(os.path.getmtime(file)) #get modified time of the file
        fileInfo.append({'name':file, 'mtime':mtime})
    return fileInfo

#Check if a port is available
def check_port_available(check_port):
    '''
    Arguments:
    check_port -- port number
    Returns:
    True if valid; False otherwise
    '''
    if str(check_port) in os.popen("netstat -na").read():
        return False
    return True

#Get the next available port by searching from initial_port to 2^16 - 1
def get_next_available_port(initial_port):
    '''
    Arguments:
    initial_port -- the first port to check

    Return:
    port found to be available; False if no any port is available.
    '''
    for port in range(initial_port, 2**16): #iterate through initial_port to 2**16 - 1
        if check_port_available(port):
            return port
    return False

class FileSynchronizer(threading.Thread):
    def __init__(self, trackerhost,trackerport,port, host='0.0.0.0'):
        threading.Thread.__init__(self)
        #Port for serving file requests
        self.port = port
        self.host = host

        #Tracker IP/hostname and port
        self.trackerhost = trackerhost
        self.trackerport = trackerport

        self.BUFFER_SIZE = 8192

        #Create a TCP socket to commuicate with tracker

        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM) 
        self.client.settimeout(180)

        #Store the message to be sent to tracker. Initialize to Init message
        #that contains port number and local file info. 

        self.msg = json.dumps({'port':self.port, 'files':get_file_info()})  #initial msg for tracker in json format

        #Create a TCP socket to serve file requests.
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            self.server.bind((self.host, self.port))
        except socket.error:
            print(('Bind failed %s' % (socket.error)))
            sys.exit()
        self.server.listen(10)

    #Not currently used. Ensure sockets are closed on disconnect
    def exit(self):
        self.server.close()

    #Handle file requests from a peer(i.e., send requested file content to peers)
    def process_message(self, conn,addr):
        #Step 1. read the file name contained in the request
        conn.settimeout(5)    #handle unexpected disconnection of a peer
        fileName = ''
        try:
            while True:
                part = conn.recv(self.BUFFER_SIZE).decode()
                fileName += part
                if len(part) < self.BUFFER_SIZE:
                    break
            #Step 2. read the file from the local directory (assumming binary file <4MB)
            f = open(fileName, 'rb')    #open the file in byte 
            fileContent = f.read()
            f.close()
            #Step 3. send the file to the requester
            conn.send(fileContent)
            print("\"" + fileName + "\""+ " has been sent")
        except:
            print("Error in File Request Message")
        conn.close()

        #Note: use socket.settimeout to handle unexpected disconnection of a peer
        #or prolonged responses to file requests

    def run(self):
        self.client.connect((self.trackerhost,self.trackerport))
        t = threading.Timer(5, self.sync)
        t.start()
        print(('Waiting for connections on port %s' % (self.port)))
        while True:
            conn, addr = self.server.accept()
            threading.Thread(target=self.process_message, args=(conn,addr)).start()

    #Send Init or KeepAlive message to tracker, handle directory response message
    #and  request files from peers
    def sync(self):
        #print(('connect to: '+self.trackerhost,self.trackerport))

        #Step 1. send self.msg (when sync is called the first time, self.msg contains
        #the Init message. Later, in Step 4, it will be populated with a KeepAlive message)
        self.client.send(self.msg.encode('utf-8'))  #send the initial message

        #Step 2. receive a directory response message from a tracker
        directory_response_message = ''
        try:    
            while True:
                part = self.client.recv(self.BUFFER_SIZE).decode()
                directory_response_message += part
                if len(part) < self.BUFFER_SIZE:
                    break
        
            directoryMsg = json.loads(directory_response_message)   #decode the Directory Message which is in json format
        except:
            print("Directory Msg Error")
            return

        #Step 3. parse the directory response message. If it contains new or
        #more up-to-date files, request the files from the respective peers and
        #set the modified time for the synced files to mtime of the respective file
        #in the directory response message 
        currentFilesInfo = get_file_info()
        currentFiles = {}
        for i in currentFilesInfo:  #make a hash table for currently existing files in the directory
            key = i['name']
            val = i['mtime']
            currentFiles[key] = val
    
        for fileName in directoryMsg:
            if fileName not in currentFiles or (directoryMsg[fileName]['mtime'] > currentFiles[fileName]):   #if the Directory Msg contains a new file or the existing file needs to updated (mtime is not the latest)
                try:
                    p2pClient = socket.socket(socket.AF_INET, socket.SOCK_STREAM)   #create a new socket for connection to the corresponding peer
                    p2pClient.connect((directoryMsg[fileName]['ip'], directoryMsg[fileName]['port']))  #connect to the corresponding peer
                    p2pClient.send(fileName.encode('utf-8'))    #send File Request Message
                    # p2pClient.recv(self.BUFFER_SIZE).decode()
                
                    receivedFile = b''  #receive the file in bytes
                    while True:
                        part = p2pClient.recv(self.BUFFER_SIZE)
                        receivedFile += part
                        if len(part) < self.BUFFER_SIZE:
                            break
                    
                    f=open(fileName, 'wb')
                    f.write(receivedFile)
                    f.close()
                    os.utime(fileName, (-1, directoryMsg[fileName]['mtime']))   #update the modified time to the latest
                    print("Received " + "\"" + fileName + "\"" + " from Peer #" + str(directoryMsg[fileName]['port']))
                    p2pClient.close()
                except:
                    print("Error in Connection to Peer")
                    continue

        #Step 4. construct a KeepAlive message
        self.msg = json.dumps({"port":self.port})

        #Step 5. start timer
        t = threading.Timer(5, self.sync)
        t.start()

if __name__ == '__main__':
    #parse command line arguments
    parser = optparse.OptionParser(usage="%prog ServerIP ServerPort")
    options, args = parser.parse_args()
    if len(args) < 1:
        parser.error("No ServerIP and ServerPort")
    elif len(args) < 2:
        parser.error("No ServerIP or ServerPort")
    else:
        if validate_ip(args[0]) and validate_port(args[1]):
            tracker_ip = args[0]
            tracker_port = int(args[1])

        else:
            parser.error("Invalid ServerIP or ServerPort")
    #get free port
    synchronizer_port = get_next_available_port(8000)
    synchronizer_thread = FileSynchronizer(tracker_ip,tracker_port,synchronizer_port)
    synchronizer_thread.start()
