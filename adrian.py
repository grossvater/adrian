#!/usr/bin/env python

import os.path
import pprint
import re
import pickle
import ConfigParser
import getpass

from optparse import OptionParser
from suds.client import Client
from suds.sudsobject import asdict, Object

__version__ = '$version'

logger = None
stdout = None
quiet = False


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
        self.start_tls = False

    @staticmethod
    def load():        
        config = Configuration()
        config_file = ConfigParser.ConfigParser()
        
        if not config_file.read(['/etc/adrian.conf', os.path.expanduser('~/.adrian/adrian.conf')]):
            print ("No configuration file found.")
        
        for sect in ('Service', 'SMTP'):
            if not config_file.has_section(sect):
                continue
            
            options = config_file.options(sect)
            for o in options:
                if not hasattr(config, o):
                    print('Unknown configuration option: ' + o)
                    continue
                setattr(config, o, config_file.get(sect, o))
        
        return config


class CaseFileException(Exception):
    pass


class AlreadyExistsException(CaseFileException):
    pass


class CaseFile(object):
    REPO_TYPE_FILE = 0
    REPO_TYPE_SEARCH = 1
    
    FILE_ID_PATTERN = r'\d+/\d+/\d{4}'
    REPO_VERSION = 2    
    DOT_FILE = '.pmr'
    DATA_FILE = 'data.repr'

    @property
    def criteria(self):
        return self._criteria
    
    @property
    def path(self):
        return self._path
    
    def __init__(self, 
                 criteria, 
                 path,
                 conf,
                 repo_type,
                 version=0, ack_version=0, repo_version=REPO_VERSION):
        self.repo_type = repo_type
        self._criteria = criteria        
        self._version = version
        self._ack_version = ack_version
        self._path = path
        self._repo_version = repo_version
        self._conf = conf        
    
    @staticmethod
    def repo_exists(path):
        if os.path.exists(path):
            return os.path.exists(os.path.join(path, CaseFile.DOT_FILE))
        
        return False
        
    @staticmethod
    def create_repo(path, criteria, repo_type, conf):
        """Creates a repository at the given path"""
        
        if repo_type == CaseFile.REPO_TYPE_FILE:
            if not CaseFile._validate_id(criteria):
                raise Exception('Invalid file number', criteria)
        
        if CaseFile.repo_exists(path):
            raise AlreadyExistsException, ('The given path already contains a repository', path)
        
        if not os.path.exists(path):
            os.makedirs(path)
            
        case_file = CaseFile(criteria, path, conf if conf else Configuration.create(), repo_type)
        case_file._update_repo_info()
        
        return case_file
        
    @staticmethod
    def load_repo(path, conf):
        """Load repository metadata from the given path.
        
        Returns metadata or null if there is no valid repository.        
        """
        case_file = None
        
        if CaseFile.repo_exists(path):
            info = {}
            with open(os.path.join(path, CaseFile.DOT_FILE)) as f:
                for l in f:
                    info.update([l[0:-1].split('=', 1)])
            
            repo_version = int(info['repoVersion'])
            if repo_version != CaseFile.REPO_VERSION:
                raise Exception("Unsupported repository version: " + str(repo_version))
             
            case_file = CaseFile(info['criteria'],
                                 path,
                                 conf,
                                 int(info['type']),
                                 version=int(info['version']),
                                 ack_version=int(info['ackVersion']),
                                 repo_version=repo_version)
                                
        return case_file
        
    def update_repo(self):
        client = Client(self._conf.service_url)
        data = None
        changed = False
        
        try:
            if self.repo_type == CaseFile.REPO_TYPE_FILE:
                data = client.service.CautareDosare(numarDosar=self._criteria)
            else:
                data = client.service.CautareDosare(numeParte=self._criteria)
        except Exception as e:
            logger.exception(e)            
            
        if not data:
            print('Can\'t retrieve data from server')
        else: 
            data = CaseFile._pickle_suds(data)
                
            if self._version == 0:
                changed = True
            else:
                old_data = None

                try:
                    with open(os.path.join(self._path, CaseFile.DATA_FILE), 'rb') as f:
                        old_data = pickle.load(f)
                except IOError as e:
                    pass
                
                changed = old_data != data
            
            if changed:
                self._version += 1        
                self._update_repo_info()
                
                with open(os.path.join(self._path, CaseFile.DATA_FILE), 'wb') as f:                
                    pickle.dump(data, f, protocol=0)
                
        return changed
    
    def mark_repo(self):
        """Mark the information available in the file as read"""
        
        news = self._version != self._ack_version
        if news:
            self._ack_version = self._version
            self._update_repo_info()
        
        return news
            
    def dump_repo(self):
        """Prints a human readable representation of the repository, for debug only"""
                        
        print("Criteria: {}\nPath: {}\nVersion: {}\nAcknowledged version: {}"
              .format(self._criteria, self._path, self._version, self._ack_version))
        
        if self._version == 0:
            print('No data yet.')
        else:
            data = None        
            
            with open(os.path.join(self._path, CaseFile.DATA_FILE), 'rb') as f:            
                data = pickle.load(f)
            
            print('File content:\n')
            pp = pprint.PrettyPrinter(indent = 2)
            pp.pprint(data)  
            
    def has_unread_info(self):
        return self._ack_version < self._version

    def _update_repo_info(self):
        meta_file = os.path.join(self._path, CaseFile.DOT_FILE)
        
        with open(meta_file, "w") as f:
            f.write('type={}\n'.format(self.repo_type))
            f.write('repoVersion={}\n'.format(self._repo_version))
            f.write('criteria={}\n'.format(self._criteria))
            f.write('version={}\n'.format(self._version))
            f.write('ackVersion={}\n'.format(self._ack_version))
    
    @staticmethod
    def _validate_id(fileId):
        return re.match(CaseFile.FILE_ID_PATTERN, fileId)
    
    @staticmethod
    def _pickle_suds(suds_object):
        begin = asdict(suds_object)
        
        for key, value in begin.iteritems():
            if isinstance(value, list):
                for i in range(len(value)):
                    value[i] = CaseFile._pickle_suds(value[i])
            elif isinstance(value, Object):
                begin[key] = CaseFile._pickle_suds(value)
            else:
                if isinstance(value, basestring):
                    begin[key] = value.encode('UTF-8')
                else:
                    begin[key] = str(value)
                
        return begin

    @staticmethod
    def _unpickle_suds(self, fact, klass, dct):
        inst = fact.create(klass)

        def fill(dct, pnt):
            for key, value in dct.iteritems():
                if isinstance(value, dict):
                    fill(value, getattr(pnt, key))
                else:
                    setattr(pnt, key, value)

        fill(dct, inst)

        return inst

    @staticmethod
    def _dump_response(self, client):
        types = []

        for d in client.sd:
            for t in d.types:
                types.append(d.xlate(t[0]))
            
        print(types)    


def notify(case_file, conf, send_email):
    body = 'IMPORTANT: There is new information available.'
    if not quiet:
        print body

    if send_email:
        if case_file.type == CaseFile.REPO_TYPE_FILE:
            subject = 'Case file ' + case_file.criteria
        else:
            subject = 'Case files search for ' + case_file.criteria

        send_mail(conf, subject, body)


def parse():
    parser = OptionParser(
        usage=
        """usage: %prog [options] command FILE_PATH

        Available commands:
          create          Create a new case file
          create-search   Create a search
          info            Print info about the case file
          test-notify     Send a test email
          dump            Print a human readable representation of the case file
          update          Synchronize local file with remote data
          mark            Mark new information in the case file as read
        """,
            version = '%prog ' + __version__)

    parser.add_option("-n", "--number",
                      action='store',
                      dest='criteria',
                      metavar='NUMBER',
                      help='Case file number, mandatory with create command')

    parser.add_option("-p", "--party",
                      action='store',
                      dest='criteria',
                      metavar='NUMBER',
                      help='Party name, mandatory with create-search command')

    parser.add_option("-m", "--notify",
                      action='store_const',
                      dest='notify',
                      const=True,
                      help='Notify via email when there is new information about your file (only for info or update command)')
   
    parser.add_option("-q", "--quiet",
                      action='store_const',
                      dest='quiet',
                      const=True,
                      help='Suppress output to console')
 
    (opts, args) = parser.parse_args()
    if len(args) != 2:
        parser.error('Wrong number of arguments')
        return None
    
    if args[0] not in ['create', 'create-search', 'info', 'test-notify', 'dump', 'update', 'mark']:
        parser.error('Unknown command: ' + args[0])
        return None
    
    if args[0] == 'create' and opts.criteria is None:
        parser.error('File number is missing')
        return None

    if args[0] == 'create-search' and opts.criteria is None:
        parser.error('The name of the party is missing')
        return None

    return opts, args[0], args[1]


def send_mail(conf, subject, body):
    from email.mime.text import MIMEText
    import smtplib

    success = False
    msg = MIMEText(body)
    msg['Subject'] = subject

    server = smtplib.SMTP()
    try:
        server.connect(conf.host, conf.port)
        if conf.start_tls:
            server.starttls()

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


def test_mail(conf):
    return send_mail(conf, 'Test from adrian.py', 'It works')


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
    if cmd == 'create':
        try:
            CaseFile.create_repo(path, opts.criteria, CaseFile.REPO_TYPE_FILE, conf)
            
            print('The case file was successfully initialized at the given path.')
        except AlreadyExistsException:
            print('The given path already contains a case file.')
    elif cmd == 'create-search':
        try:
            CaseFile.create_repo(path, opts.criteria,  CaseFile.REPO_TYPE_SEARCH, conf)
            
            print('The search was successfully initialized at the given path.')
        except AlreadyExistsException:
            print('The given path already contains a repository.')
    elif cmd == 'dump':
        case_file = CaseFile.load_repo(path, conf)
        
        if not case_file:
            print('No valid case file at: ' + path)
        else:
            case_file.dump_repo()
    elif cmd == 'update':
        case_file = CaseFile.load_repo(path, conf)

        if not case_file:
            print('No valid case file at: ' + path)        
        elif case_file.update_repo():
            if case_file.has_unread_info():
                notify(case_file, conf, opts.notify)
        else:
            print('There is nothing new in your case file.')
        
    elif cmd == 'mark':
        case_file = CaseFile.load_repo(path, conf)

        if not case_file:
            print('No valid case file at: ' + path)
        else:
            if not case_file.mark_repo():
                print('There is nothing new in your case file.')
            else:
                print('The new information in your file have been marked as read')
        
    elif cmd == 'info':
        case_file = CaseFile.load_repo(path, conf)
        if not case_file:
            print('No valid case file at: ' + path)
        else:
            print("File id: {}\nPath: {}"
                  .format(case_file.criteria,
                          case_file.path))
            
            if case_file.has_unread_info():
                notify(case_file, conf, opts.notify)
                
    elif cmd == 'test-notify':
        if test_mail(conf):
            print('Mail test succeeded')
        else:
            print('Mail test failed')
            
if __name__ == "__main__":
    main()
