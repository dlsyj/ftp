import socket, sys, os, threading, time

listenAddr = '127.0.0.1'
listenPort = 12344

def log(message, clientAddr = None):
    ''' Write log '''
    if clientAddr == None:
        print('\033[92m[%s]\033[0m %s' % (time.strftime(r'%H:%M:%S, %m.%d.%Y'), message))
    else:
        print('\033[92m[%s] %s:%d\033[0m %s' % (time.strftime(r'%H:%M:%S, %m.%d.%Y'), clientAddr[0], clientAddr[1], message))

class DataSockListener(threading.Thread):
    ''' Asynchronously accepts data connections '''
    def __init__(self, server):
        super().__init__()
        self.daemon = True # Daemon
        self.server = server
        self.listenSock = server.dataListenSock
    def run(self):
        self.listenSock.settimeout(1.0) # Check for every 1 second
        while True:
            try:
                (dataSock, clientAddr) = self.listenSock.accept()
            except (socket.timeout):
                pass
            except (socket.error): # Stop when socket closes
                break
            else:
                if self.server.dataSock != None: # Existing data connection not closed, cannot accept
                    dataSock.close()
                    log('Data connection refused from %s:%d.' % (clientAddr[0], clientAddr[1]), self.server.clientAddr)
                else:
                    self.server.dataSock = dataSock
                    log('Data connection accpted from %s:%d.' % (clientAddr[0], clientAddr[1]), self.server.clientAddr)

class FTPServer(threading.Thread):
    ''' FTP server handler '''
    def __init__(self, controlSock, clientAddr):
        super().__init__()
        self.daemon = True # Daemon
        self.bufSize = 1024
        self.controlSock = controlSock
        self.clientAddr = clientAddr
        self.dataListenSock = None
        self.dataSock = None
        self.dataAddr = '127.0.0.1'
        self.dataPort = None
        self.username = ''
        self.authenticated = False
        self.cwd = os.getcwd()
        self.typeMode = 'Binary'
        self.dataMode = 'PORT'
    def run(self):
        self.controlSock.send(b'220 Service ready for new user.\r\n')
        while True:
            cmd = self.controlSock.recv(self.bufSize).decode('ascii')
            if cmd == '': # Connection closed
                self.controlSock.close()
                log('Client disconnected.', self.clientAddr)
                break
            log('[' + (self.username if self.authenticated else '') + '] ' + cmd.strip(), self.clientAddr)
            cmdHead = cmd.split()[0].upper()
            if cmdHead == 'QUIT': # QUIT
                self.controlSock.send(b'221 Service closing control connection. Logged out if appropriate.\r\b')
                self.controlSock.close()
                log('Client disconnected.', self.clientAddr)
                break
            elif cmdHead == 'HELP': # HELP
                self.controlSock.send(b'214 QUIT HELP USER PASS PWD CWD TYPE PASV NLST RETR STOR\r\n')
            elif cmdHead == 'USER': # USER
                if len(cmd.split()) < 2:
                    self.controlSock.send(b'501 Syntax error in parameters or arguments.\r\n')
                else:
                    self.username = cmd.split()[1]
                    self.controlSock.send(b'331 User name okay, need password.\r\n')
                    self.authenticated = False
            elif cmdHead == 'PASS': # PASS
                if self.username == '':
                    self.controlSock.send(b'503 Bad sequence of commands.\r\n')
                else:
                    if len(cmd.split()) < 2:
                        self.controlSock.send(b'501 Syntax error in parameters or arguments.\r\n')
                    else:
                        self.controlSock.send(b'230 User logged in, proceed.\r\n')
                        self.authenticated = True
            elif cmdHead == 'PWD': # PWD
                if not self.authenticated:
                    self.controlSock.send(b'530 Not logged in.\r\n')
                else:
                    self.controlSock.send(('257 "%s" is the current directory.\r\n' % self.cwd).encode('ascii'))
            elif cmdHead == 'CWD': # CWD
                if not self.authenticated:
                    self.controlSock.send(b'530 Not logged in.\r\n')
                elif len(cmd.split()) < 2:
                    self.controlSock.send(('250 "%s" is the current directory.\r\n' % self.cwd).encode('ascii'))
                else:
                    programDir = os.getcwd()
                    os.chdir(self.cwd)
                    newDir = cmd.split()[1]
                    try:
                        os.chdir(newDir)
                    except (OSError):
                        self.controlSock.send(b'550 Requested action not taken. File unavailable (e.g., file busy).\r\n')
                    else:
                        self.cwd = os.getcwd()
                        self.controlSock.send(('250 "%s" is the current directory.\r\n' % self.cwd).encode('ascii'))
                    os.chdir(programDir)
            elif cmdHead == 'TYPE': # TYPE, currently only I is supported
                if not self.authenticated:
                    self.controlSock.send(b'530 Not logged in.\r\n')
                elif len(cmd.split()) < 2:
                    self.controlSock.send(b'501 Syntax error in parameters or arguments.\r\n')
                elif cmd.split()[1] == 'I':
                    self.typeMode = 'Binary'
                    self.controlSock.send(b'200 Type set to: Binary.\r\n')
                else:
                    self.controlSock.send(b'504 Command not implemented for that parameter.\r\n')
            elif cmdHead == 'PASV': # PASV, currently only support PASV
                if not self.authenticated:
                    self.controlSock.send(b'530 Not logged in.\r\n')
                else:
                    if self.dataListenSock != None: # Close existing data connection listening socket
                        self.dataListenSock.close()
                    self.dataListenSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
                    self.dataListenSock.bind((self.dataAddr, 0))
                    self.dataPort = self.dataListenSock.getsockname()[1]
                    self.dataListenSock.listen(5)
                    self.dataMode = 'PASV'
                    DataSockListener(self).start()
                    time.sleep(0.5) # Wait for connection to set up
                    self.controlSock.send(('227 Entering passive mode (%s,%s,%s,%s,%d,%d)\r\n' % (self.dataAddr.split('.')[0], self.dataAddr.split('.')[1], self.dataAddr.split('.')[2], self.dataAddr.split('.')[3], int(self.dataPort / 256), self.dataPort % 256)).encode('ascii'))
            elif cmdHead == 'NLST': # NLST
                if not self.authenticated:
                    self.controlSock.send(b'530 Not logged in.\r\n')
                elif self.dataMode == 'PASV' and self.dataSock != None: # Only PASV implemented
                    self.controlSock.send(b'125 Data connection already open. Transfer starting.\r\n')
                    directory = '\r\n'.join(os.listdir(self.cwd)) + '\r\n'
                    self.dataSock.send(directory.encode('ascii'))
                    self.dataSock.close()
                    self.dataSock = None
                    self.controlSock.send(b'225 Closing data connection. Requested file action successful (for example, file transfer or file abort).\r\n')
                else:
                    self.controlSock.send(b"425 Can't open data connection.\r\n")
            elif cmdHead == 'RETR':
                if not self.authenticated:
                    self.controlSock.send(b'530 Not logged in.\r\n')
                elif len(cmd.split()) < 2:
                    self.controlSock.send(b'501 Syntax error in parameters or arguments.\r\n')
                elif self.dataMode == 'PASV' and self.dataSock != None: # Only PASV implemented
                    programDir = os.getcwd()
                    os.chdir(self.cwd)
                    self.controlSock.send(b'125 Data connection already open; transfer starting.\r\n')
                    fileName = cmd.split()[1]
                    try:
                        self.dataSock.send(open(fileName, 'rb').read())
                    except (IOError):
                        self.controlSock.send(b'550 Requested action not taken. File unavailable (e.g., file busy).\r\n')
                    self.dataSock.close()
                    self.dataSock = None
                    self.controlSock.send(b'225 Closing data connection. Requested file action successful (for example, file transfer or file abort).\r\n')
                    os.chdir(programDir)
                else:
                    self.controlSock.send(b"425 Can't open data connection.\r\n")
            elif cmdHead == 'STOR':
                if not self.authenticated:
                    self.controlSock.send(b'530 Not logged in.\r\n')
                elif len(cmd.split()) < 2:
                    self.controlSock.send(b'501 Syntax error in parameters or arguments.\r\n')
                elif self.dataMode == 'PASV' and self.dataSock != None: # Only PASV implemented
                    programDir = os.getcwd()
                    os.chdir(self.cwd)
                    self.controlSock.send(b'125 Data connection already open; transfer starting.\r\n')
                    fileOut = open(cmd.split()[1], 'wb')
                    time.sleep(0.5) # Wait for connection to set up
                    self.dataSock.setblocking(False) # Set to non-blocking to detect connection close
                    while True:
                        try:
                            data = self.dataSock.recv(self.bufSize)
                            if data == b'': # Connection closed
                                break
                            fileOut.write(data)
                        except (socket.error): # Connection closed
                            break
                    fileOut.close()
                    self.dataSock.close()
                    self.dataSock = None
                    self.controlSock.send(b'225 Closing data connection. Requested file action successful (for example, file transfer or file abort).\r\n')
                    os.chdir(programDir)
                else:
                    self.controlSock.send(b"425 Can't open data connection.\r\n")

if __name__ == '__main__':
    listenSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
    listenSock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listenSock.bind((listenAddr, listenPort))
    listenSock.listen(5)
    log('Server started.')
    while True:
        (controlSock, clientAddr) = listenSock.accept()
        FTPServer(controlSock, clientAddr).start()
        log("Connection accepted.", clientAddr)
