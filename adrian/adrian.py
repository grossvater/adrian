import optparse
import os.path
import os
import pprint
import re
import suds.client
import pickle
#import dns.resolver
import ConfigParser
import getpass

from optparse import OptionParser
from suds.client import Client
from suds.sudsobject import asdict, Object

__version__ = '0.3'

logger = None
stdout = None
quiet = False
              
file_number = None

class Configuration(object):
    SERVICE_URL = 'http://portalquery.just.ro/query.asmx?wsdl'
    
    def __init__(self):
        self.service_url = Configuration.SERVICE_URL
        self.host = 'localhost'
        self.port = 25        
        self.user = getpass.getuser()
        self.password = None
        self.mailto = self.user
        self.mailfrom = self.user
                
    @staticmethod
    def load():        
        config = Configuration()
        configFile = ConfigParser.ConfigParser()
        
        if not configFile.read(['/etc/adrian.conf', os.path.expanduser('~/.adrian/adrian.conf')]):
            print ("No configuration file found.")
        
        for sect in ('Service', 'SMTP'):
            if not configFile.has_section(sect):
                continue
            
            options = configFile.options(sect)
            for o in options:
                if not hasattr(config, o):
                    print('Unknown configuration option: ' + o)
                    continue
                setattr(config, o, configFile.get(sect, o))
        
        return config

class CaseFileException(Exception):
    pass

class AlreadyExistsException(CaseFileException):
    pass
    
class CaseFile(object):
    FILE_ID_PATTERN = r'\d+/\d+/\d{4}'
    REPO_VERSION = '1'    
    DOT_FILE = '.pmr'
    DATA_FILE = 'data.repr'

    @property
    def fileNumber(self):
        return self._id
    
    @property
    def path(self):
        return self._path
    
    def __init__(self, id, path,
                 conf,
                 version = 0, ackVersion = 0, repoVersion = REPO_VERSION):
        self._id = id
        self._version = version
        self._ackVersion = ackVersion
        self._path = path
        self._repoVersion = repoVersion
        self._conf = conf        
    
    
    @staticmethod
    def repoExists(path):
        if os.path.exists(path):
            return os.path.exists(os.path.join(path, CaseFile.DOT_FILE))
        
        return False
        
    @staticmethod
    def createRepo(path, id, conf):
        """Creates a repository at the given path"""
        
        if not CaseFile._validateId(id):
            raise Exception('Invalid file number', id)
        
        if CaseFile.repoExists(path):
            raise AlreadyExistsException, ('The given path already contains a repository', path)
        
        if not os.path.exists(path):
            os.makedirs(path)
            
        caseFile = CaseFile(id, path, conf if conf else Configuration.create())
        caseFile._updateRepoInfo()
        
        return caseFile
    
    @staticmethod
    def loadRepo(path, conf):
        """Load repository metadata from the given path.
        
        Returns metadata or null if there is no valid repository.        
        """
        caseFile = None
        
        if CaseFile.repoExists(path):
            info = {}
            with open(os.path.join(path, CaseFile.DOT_FILE)) as f:
                for l in f:
                    info.update([l[0:-1].split('=', 1)])
                
            caseFile = CaseFile(info['id'], path, 
                                conf,
                                version = int(info['version']),
                                ackVersion = int(info['ackVersion']),
                                repoVersion = int(info['repoVersion']))
                                
        return caseFile
        
    def updateRepo(self):
        client = Client(self._conf.service_url)
        data = client.service.CautareDosare(self._id)
        data = CaseFile._pickleSuds(data)
        changed = False
            
        if self._version == 0:
            changed = True
        else:
            oldData = None
            
            with open(os.path.join(self._path, CaseFile.DATA_FILE), 'rb') as f:            
                oldData = pickle.load(f)
            
            changed = oldData != data
        
        if changed:
            self._version += 1        
            self._updateRepoInfo()    
            
            with open(os.path.join(self._path, CaseFile.DATA_FILE), 'wb') as f:                
                pickle.dump(data, f, protocol = 0)
                
        return changed
    
    def markRepo(self):
        """Mark the information available in the file as read"""
        
        news = self._version != self._ackVersion
        if news:
            self._ackVersion = self._version
            self._updateRepoInfo()
        
        return news
            
    def dumpRepo(self):
        """Prints a human readable representation of the repository, for debug only"""
                        
        print("Id: {}\nPath: {}\nVersion: {}\nAcknowledged version: {}"
              .format(self._id, self._path, self._version, self._ackVersion))
        
        if self._version == 0:
            print('No data yet.')
        else:
            data = None        
            
            with open(os.path.join(self._path, CaseFile.DATA_FILE), 'rb') as f:            
                data = pickle.load(f)
            
            print('File content:\n')
            pp = pprint.PrettyPrinter(indent = 2)
            pp.pprint(data)  
            
    def hasUnreadInfo(self):
        return self._ackVersion < self._version

    def _updateRepoInfo(self):
        metaFile = os.path.join(self._path, CaseFile.DOT_FILE)
        
        with open(metaFile, "w") as f:
            f.write('repoVersion={}\n'.format(self._repoVersion))
            f.write('id={}\n'.format(self._id))
            f.write('version={}\n'.format(self._version))
            f.write('ackVersion={}\n'.format(self._ackVersion))   
    
    @staticmethod
    def _validateId(id):
        return re.match(CaseFile.FILE_ID_PATTERN, id)
    
    @staticmethod
    def _pickleSuds(sobject):
        begin = asdict(sobject)
        
        for key, value in begin.iteritems():
            if isinstance(value, list):
                for i in range(len(value)):
                    value[i] = CaseFile._pickleSuds(value[i])
            elif isinstance(value, Object):
                begin[key] = CaseFile._pickleSuds(value)
            else:
                if isinstance(value, basestring):
                    begin[key] = value.encode('UTF-8')
                else:
                    begin[key] = str(value)
                
        return begin
            
    def _unpickleSuds(self, fact, klass, dct):
        inst = fact.create(klass)

        def fill(dct, pnt):
            for key, value in dct.iteritems():
                if isinstance(value, dict):
                    fill(value, getattr(pnt, key))
                else:
                    setattr(pnt, key, value)

        fill(dct, inst)

        return inst
        
    def _dumpResponse(self, client):
        types = []

        for d in client.sd:
            for t in d.types:
                types.append(d.xlate(t[0]))
            
        print(types)    

def notify(caseFile, notify):
    print('IMPORTANT: There is new information available in your case file.')
                    
def parse():
    parser = OptionParser(usage = 
"""usage: %prog [options] command FILE_PATH
    
Available commands:
  create          Create a new case file
  info            Print info about the case file
  test-notify     Send a test email 
  dump            Print a human readable representation of the case file
  update          Synchronize local file with remote data
  mark            Mark new information in the case file as read
""",
                          version = '%prog ' + __version__)
    
    parser.add_option("-n", "--number",
                      action = 'store',
                      dest = 'file_number',
                      metavar = 'NUMBER',
                      help = 'Case file number, mandatory with create command')
                            
    parser.add_option("-m", "--notify",
                      action = 'store_const',
                      dest = 'notify',
                      const = True,
                      help = 'Notify via email when there is new information about your file (when create or info command is supplied)')
   
    parser.add_option("-q", "--quiet",
                      action = 'store_const',
                      dest = 'quiet',
                      const = True,
                      help = 'Suppress output to console')
 
    (opts, args) = parser.parse_args()
    if len(args) != 2:
        parser.error('Wrong number of arguments')
        return None
    
    if args[0] not in ['create', 'info', 'test-notify', 'dump', 'update', 'mark']:
        parser.error('Unknown command: ' + args[0])
        return None
    
    return (opts, args[0], args[1])

def test_mail(conf):    
    from email.mime.text import MIMEText
    import smtplib

    success = False
    msg = MIMEText('It works!')
    msg['Subject'] = 'Test from adrian.py'
    
    server = smtplib.SMTP()
    try:
        server.connect(conf.host, conf.port)
        
        if conf.user:
            server.login(conf.user, conf.password)
        server.sendmail(conf.mailfrom, conf.mailto, msg.as_string())
        success = True
    except Exception as e:
        logger.exception(e)
        pass
    finally:
        server.quit
        
    return success

def init_console(quiet):
    if quiet:        
        import sys
        
        logger.info('Quiet mode ON, all console output redirected to log file.')
        class Console(object):
            def __init__(self, logger):
                self.logger = logger
                
            def write(self, s):
                if s[-1:] != '\n':
                    # remove empty lines
                    self.logger.info(s)
        
        global stdout
        
        stdout = sys.stdout
        
        sys.stdout = Console(logger)

def init_log():
    import logging
    
    global logger
    
    path = os.path.expanduser('~/.adrian/log')
    if not os.path.exists(path):
        os.makedirs(path)
    path = os.path.join(path, 'adrian.log')
    
    logging.basicConfig(filename=path,
                        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                        level=logging.DEBUG)
    logger = logging.getLogger()
    
    # hide suds bug https://fedorahosted.org/suds/ticket/444
    logging.getLogger('suds')\
           .setLevel(logging.INFO)
    
def main():
    init_log()
    
    r = parse()
    
    if not r:
        return
    
    (opts, cmd, path) = r
    
    init_console(opts.quiet)
        
    conf = Configuration.load()
    if (cmd == 'create'):
        try:
            CaseFile.createRepo(path, opts.file_number, conf)
            
            print('The case file was successfully initialized at the given path.')
        except AlreadyExistsException:
            print('The given path already contains a case file.')
    elif (cmd == 'dump'):
        caseFile = CaseFile.loadRepo(path, conf)
        
        if not caseFile:
            print('No valid case file at: ' + path)
        else:
            caseFile.dumpRepo()
    elif (cmd == 'update'):
        caseFile = CaseFile.loadRepo(path, conf)

        if not caseFile:
            print('No valid case file at: ' + path)        
        elif caseFile.updateRepo():        
            if caseFile.hasUnreadInfo():
                notify(caseFile, opts.notify)
        else:
            print('There is nothing new in your case file.')
        
    elif (cmd == 'mark'):
        news = False
        caseFile = CaseFile.loadRepo(path, conf)
        if not caseFile:
            print('No valid case file at: ' + path)
        else:
            news = caseFile.markRepo()
            if not news:
                print('There is nothing new in your case file.')
            else:
                print('The new information in your file have been marked as read')
        
    elif (cmd == 'info'):
        caseFile = CaseFile.loadRepo(path, conf)
        if not caseFile:
            print('No valid case file at: ' + path)
        else:
            print("File id: {}\nPath: {}"
                  .format(caseFile.fileNumber,
                          caseFile.path))
            
            if caseFile.hasUnreadInfo():
                notify(caseFile, opts.notify)
                
    elif (cmd == 'test-notify'):
        if test_mail(conf):
            print('Mail test succeded')
        else:
            print('Mail test failed')
            
if __name__ == "__main__":
    main()
