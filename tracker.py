import socket, sys, threading, json,time,optparse,os

def validate_ip(s):
    """
    Check if an input string is a valid IP address dot decimal format
    Inputs:
    - a: a string

    Output:
    - True or False
    """
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

def validate_port(x):
    """
    Check if the port number is within range
    Inputs:
    - x: port number

    Output:
    - True or False
    """
    if not x.isdigit():
        return False
    i = int(x)
    if i < 0 or i > 65535:
            return False
    return True

class Tracker(threading.Thread):
    def __init__(self, port, host='0.0.0.0'):
        threading.Thread.__init__(self)
        self.port = port #port used by tracker
        self.host = host #tracker's IP address
        self.BUFFER_SIZE = 8192
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM) #TCP socket to accept connections from peers

        #Track (ip, port, exp time) for each peer using a dictionary
        self.users = {}

        #Track (ip, port, modified time) for each file
        #Only the most recent modified time and the respective peer are store
        #{'ip':,'port':,'mtime':}
        self.files = {}

        self.lock = threading.Lock()
        try:
            #Bind to address and port
            self.server.bind((self.host, self.port))
        except socket.error:
            print(('Bind failed %s' % (socket.error)))
            sys.exit()

        #listen for connections
        self.server.listen()

    def check_user(self):
        #Check if the peers are alive or not
        #self.users ==> key = (ip, port), value = time the entry was created
        #self.files ==> key = file name, value = dictionary of ip, port and modified time
        delUser = []
        delFile = []

        self.lock.acquire()
        for usersKey, usersVal in self.users.items():
            print("Checking Peer #" + str(usersKey[1]))
            if (time.time() - usersVal) > 180: #check if time has not been modified for 180 seconds 
                print("Peer #" + str(usersKey[1]) +  " has expired")
                for filesKey, filesVal in self.files.items():
                    if filesVal['port'] == usersKey[1]:    #search for corresponding file with the peer's port
                        delFile.append(filesKey) #append to delFile list to delete after the iteration (so the dictionary size does not change)
                delUser.append(usersKey) 
        
        for user in delUser:
            del self.users[user]
            print("Peer #" + str(user[1]) + " is deleted")
        for file in delFile:
            del self.files[file]
        self.lock.release()

        #schedule the method to be called periodically
        t = threading.Timer(20, self.check_user)
        t.start()

    #Ensure sockets are closed on disconnect (This function is Not used)
    def exit(self):
        self.server.close()

    def run(self):
        #start the timer to check if peers are alive or not (repeats every 20 sec)
        t = threading.Timer(20, self.check_user)
        t.start()

        print(('Waiting for connections on port %s' % (self.port)))
        while True:
            #accept incoming connection
            conn, addr = self.server.accept()

            #process the message from a peer (start a new thread)
            threading.Thread(target=self.process_messages, args=(conn, addr)).start()

    def process_messages(self, conn, addr):
        conn.settimeout(180.0)
        print(('Client connected with ' + addr[0] + ':' + str(addr[1])))

        while True:
            #receiving data from a peer
            data = ''
            while True:
                part = conn.recv(self.BUFFER_SIZE).decode()
                data = data + part
                if len(part) < self.BUFFER_SIZE:
                    break

            #Check if the received data is a json string of the anticipated format. If not, ignore.
            try:
                data_dic = json.loads(data)
            except ValueError:
                continue
            
            #deserialize
            #data_dic = json.loads(data)
            #print(data_dic) #testing received msgs

            #sample data_dic ==> {'port': 8001, 'files': [{'mtime': 1548878750.8774116, 'name': 'fileA.txt'}]}
            #self.users ==> key = (ip, port), value = time the entry was created
            #self.files ==> key = file name, value = dictionary of ip, port and modified time
            self.lock.acquire()

            if 'port' in data_dic.keys(): #check if the received message is valid 
                userKey = (addr[0], data_dic['port']) 
                #Initial Message
                if 'files' in data_dic.keys():
                    #Upload Peer and File Information
                    if userKey not in self.users.keys(): #create an entry of a peer in self.users if there is none
                        self.users[userKey] = time.time()  #key = (ip, port) , value = time the entry was created

                    for fileData in data_dic['files']: #check if entry for each file (from the list of files received) exist in self.files
                        fileName = fileData['name']
                        if fileName not in self.files: #create an entry of the file in self.files if there is none
                            self.files[fileName] = {'ip':addr[0], 'port':data_dic['port'], 'mtime':fileData['mtime']} #key = file name, value = dictionary of ip, port and modified time
                        else: #update the entry of the file if it already exists
                            fileMetaData = self.files[fileName] #fileMetaData contains ip, port and modified time of the file
                            if fileMetaData['mtime'] < fileData['mtime']: #when newley received file has recent (biggest) modified time then replace to the recent one 
                                fileMetaData['mtime'] = fileData['mtime']
                                fileMetaData['port'] = data_dic['port'] #if multiple files from different peers have the same file name, the one with the latest modified timestamp will be kept by the tracker

                #Keep-Alive Message
                else: 
                    self.users[userKey] = time.time() #update expire time

            self.lock.release()

            #Tracker Responds with a Directory Message
            conn.send(json.dumps(self.files).encode('utf-8'))
            # print("Users:", self.users)
            # print("Files:", self.files)

        conn.close() #Close

if __name__ == '__main__':
    parser = optparse.OptionParser(usage="%prog ServerIP ServerPort")
    options, args = parser.parse_args()
    if len(args) < 1:
        parser.error("No ServerIP and ServerPort")
    elif len(args) < 2:
        parser.error("No  ServerIP or ServerPort")
    else:
        if validate_ip(args[0]) and validate_port(args[1]):
            server_ip = args[0]
            server_port = int(args[1])
        else:
            parser.error("Invalid ServerIP or ServerPort")
    tracker = Tracker(server_port,server_ip)
    tracker.start()
