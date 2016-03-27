""" Take care of archives formats
"""

import logging
import os
import shutil
import stat
import tarfile
import tempfile
import zipfile

from libmat import parser

# Zip files do not support dates older than 01/01/1980
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class GenericArchiveStripper(parser.GenericParser):
    """ Represent a generic archive
    """

    def get_meta(self):
        raise NotImplementedError

    def __init__(self, filename, mime, backup, is_writable, **kwargs):
        super(GenericArchiveStripper, self).__init__(filename, mime, backup, is_writable, **kwargs)
        self.compression = ''
        self.add2archive = kwargs['add2archive']
        self.tempdir = tempfile.mkdtemp()

    def __del__(self):
        """ Remove the files inside the temp dir,
            then remove the temp dir
        """
        for root, _, files in os.walk(self.tempdir):
            for item in files:
                from libmat.mat import secure_remove
                path_file = os.path.join(root, item)
                secure_remove(path_file)
        shutil.rmtree(self.tempdir)

    def is_clean(self, list_unsupported=False):
        """ Virtual method to check for harmul metadata
        :param bool list_unsupported:
        """
        raise NotImplementedError

    def list_unsupported(self):
        """ Get a list of every non-supported files present in the archive
        """
        return self.is_clean(list_unsupported=True)

    def remove_all(self):
        """ Virtual method to remove all compromising fields
        """
        raise NotImplementedError


class ZipStripper(GenericArchiveStripper):
    """ Represent a zip file
    """

    @staticmethod
    def __is_zipfile_clean(fileinfo):
        """ Check if a ZipInfo object is clean of metadata added
            by zip itself, independently of the corresponding file metadata
        """
        if fileinfo.comment != '':
            return False
        elif fileinfo.date_time != ZIP_EPOCH:
            return False
        elif fileinfo.create_system != 3:  # 3 is UNIX
            return False
        return True

    def is_clean(self, list_unsupported=False):
        """ Check if the given file is clean from harmful metadata
            When list_unsupported is True, the method returns a list
            of all non-supported/archives files contained in the
            archive.

            :param bool list_unsupported: Should the list of unsupported files be returned
        """
        ret_list = []
        zipin = zipfile.ZipFile(self.filename, 'r')
        if zipin.comment != '' and not list_unsupported:
            logging.debug('%s has a comment', self.filename)
            return False
        for item in zipin.infolist():
            zipin.extract(item, self.tempdir)
            path = os.path.join(self.tempdir, item.filename)
            if not self.__is_zipfile_clean(item) and not list_unsupported:
                logging.debug('%s from %s has compromising zipinfo', item.filename, self.filename)
                return False
            if os.path.isfile(path):
                from libmat.mat import create_class_file
                cfile = create_class_file(path, False, add2archive=self.add2archive)
                if cfile is not None:
                    if not cfile.is_clean():
                        logging.debug('%s from %s has metadata', item.filename, self.filename)
                        if not list_unsupported:
                            return False
                else:
                    logging.info('%s\'s fileformat is not supported or harmless.', item.filename)
                    _, ext = os.path.splitext(path)
                    if os.path.basename(item.filename) not in ('mimetype', '.rels'):
                        if ext not in parser.NOMETA:
                            if not list_unsupported:
                                return False
                            ret_list.append(item.filename)
        zipin.close()
        if list_unsupported:
            return ret_list
        return True

    def get_meta(self):
        """ Return all the metadata of a zip archive"""
        zipin = zipfile.ZipFile(self.filename, 'r')
        metadata = {}
        if zipin.comment != '':
            metadata['comment'] = zipin.comment
        for item in zipin.infolist():
            zipinfo_meta = self.__get_zipinfo_meta(item)
            if zipinfo_meta != {}:  # zipinfo metadata
                metadata[item.filename + "'s zipinfo"] = str(zipinfo_meta)
            zipin.extract(item, self.tempdir)
            path = os.path.join(self.tempdir, item.filename)
            if os.path.isfile(path):
                from libmat.mat import create_class_file
                cfile = create_class_file(path, False, add2archive=self.add2archive)
                if cfile is not None:
                    cfile_meta = cfile.get_meta()
                    if cfile_meta != {}:
                        metadata[item.filename] = str(cfile_meta)
                else:
                    logging.info('%s\'s fileformat is not supported or harmless', item.filename)
        zipin.close()
        return metadata

    @staticmethod
    def __get_zipinfo_meta(zipinfo):
        """ Return all the metadata of a ZipInfo
        """
        metadata = {}
        if zipinfo.comment != '':
            metadata['comment'] = zipinfo.comment
        if zipinfo.date_time != ZIP_EPOCH:
            metadata['modified'] = zipinfo.date_time
        if zipinfo.create_system != 3:  # 3 is UNIX
            metadata['system'] = "windows" if zipinfo.create_system == 2 else "unknown"
        return metadata

    def remove_all(self, whitelist=None, beginning_blacklist=None, ending_blacklist=None):
        """ Remove all metadata from a zip archive, even thoses
            added by Python's zipfile itself. It will not add
            files starting with "begining_blacklist", or ending with
            "ending_blacklist". This method also add files present in
            whitelist to the archive.

            :param list whitelist: Add those files to the produced archive, regardless if they are harmful or not
            :param list beginning_blacklist: If the file starts with $ending_blacklist, it will _not_ be added
            :param list ending_blacklist: If the file end with $ending_blacklist, it will _not_ be added
        """
        if not ending_blacklist:
            ending_blacklist = []
        if not beginning_blacklist:
            beginning_blacklist = []
        if not whitelist:
            whitelist = []
        zipin = zipfile.ZipFile(self.filename, 'r')
        zipout = zipfile.ZipFile(self.output, 'w', allowZip64=True)
        for item in zipin.infolist():
            zipin.extract(item, self.tempdir)
            path = os.path.join(self.tempdir, item.filename)

            beginning = any((True for f in beginning_blacklist if item.filename.startswith(f)))
            ending = any((True for f in ending_blacklist if item.filename.endswith(f)))

            if os.path.isfile(path) and not beginning and not ending:
                from libmat.mat import create_class_file
                cfile = create_class_file(path, False, add2archive=self.add2archive)
                if cfile is not None:
                    # Handle read-only files inside archive
                    old_stat = os.stat(path).st_mode
                    os.chmod(path, old_stat | stat.S_IWUSR)
                    cfile.remove_all()
                    os.chmod(path, old_stat)
                    logging.debug('Processing %s from %s', item.filename, self.filename)
                elif item.filename not in whitelist:
                    logging.info("%s's format is not supported or harmless", item.filename)
                    _, ext = os.path.splitext(path)
                    if not (self.add2archive or ext in parser.NOMETA):
                        continue
                zinfo = zipfile.ZipInfo(item.filename, date_time=ZIP_EPOCH)
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                zinfo.create_system = 3  # Linux
                zinfo.comment = ''
                with open(path, 'r') as f:
                    zipout.writestr(zinfo, f.read())
                # os.utime(path, (ZIP_EPOCH_SECONDS, ZIP_EPOCH_SECONDS))
                # zipout.write(path, item.filename)
        zipin.close()
        zipout.close()

        logging.info('%s processed', self.filename)
        self.do_backup()
        return True


class TarStripper(GenericArchiveStripper):
    """ Represent a tarfile archive
    """

    @staticmethod
    def _remove_tar_added(current_file):
        """ Remove the meta added by tarfile itself to the file
        """
        current_file.mtime = 0
        current_file.uid = 0
        current_file.gid = 0
        current_file.uname = ''
        current_file.gname = ''
        return current_file

    def remove_all(self, whitelist=None):
        """ Remove all harmful metadata from the tarfile.
            The method will also add every files matching
            whitelist in the produced archive.
            :param list whitelist: Files to add the to produced archive,
                    regardless if they are considered harmfull.
        """
        if not whitelist:
            whitelist = []
        tarin = tarfile.open(self.filename, 'r' + self.compression, encoding='utf-8')
        tarout = tarfile.open(self.output, 'w' + self.compression, encoding='utf-8')
        for item in tarin.getmembers():
            tarin.extract(item, self.tempdir)
            if item.isfile():
                path = os.path.join(self.tempdir, item.name)
                from libmat.mat import create_class_file
                cfile = create_class_file(path, False, add2archive=self.add2archive)
                if cfile is not None:
                    # Handle read-only files inside archive
                    old_stat = os.stat(path).st_mode
                    os.chmod(path, old_stat | stat.S_IWUSR)
                    cfile.remove_all()
                    os.chmod(path, old_stat)
                elif self.add2archive or os.path.splitext(item.name)[1] in parser.NOMETA:
                    logging.debug("%s' format is either not supported or harmless", item.name)
                elif item.name in whitelist:
                    logging.debug('%s is not supported, but MAT was told to add it anyway.', item.name)
                else:  # Don't add the file to the archive
                    logging.debug('%s will not be added', item.name)
                    continue
                tarout.add(unicode(path.decode('utf-8')),
                           unicode(item.name.decode('utf-8')),
                           filter=self._remove_tar_added)
        tarin.close()
        tarout.close()
        self.do_backup()
        return True

    @staticmethod
    def is_file_clean(current_file):
        """ Check metadatas added by tarfile
        :param tarfile.TarInfo current_file:
        """
        if current_file.mtime != 0:
            return False
        elif current_file.uid != 0:
            return False
        elif current_file.gid != 0:
            return False
        elif current_file.uname != '':
            return False
        elif current_file.gname != '':
            return False
        return True

    def is_clean(self, list_unsupported=False):
        """ Check if the file is clean from harmful metadatas
            When list_unsupported is True, the method returns a list
            of all non-supported/archives files contained in the
            archive.
            :param bool list_unsupported:
        """
        ret_list = []
        tarin = tarfile.open(self.filename, 'r' + self.compression)
        for item in tarin.getmembers():
            if not self.is_file_clean(item) and not list_unsupported:
                logging.debug('%s from %s has compromising tarinfo', item.name, self.filename)
                return False
            tarin.extract(item, self.tempdir)
            path = os.path.join(self.tempdir, item.name)
            if item.isfile():
                from libmat.mat import create_class_file
                cfile = create_class_file(path, False, add2archive=self.add2archive)
                if cfile is not None:
                    if not cfile.is_clean():
                        logging.debug('%s from %s has metadata', item.name.decode("utf8"), self.filename)
                        if not list_unsupported:
                            return False
                        # Nested archives are treated like unsupported files
                        elif isinstance(cfile, GenericArchiveStripper):
                            ret_list.append(item.name)
                else:
                    logging.info("%s's format is not supported or harmless", item.name)
                    if os.path.splitext(path)[1] not in parser.NOMETA:
                        if not list_unsupported:
                            return False
                        ret_list.append(item.name)
        tarin.close()
        if list_unsupported:
            return ret_list
        return True

    def get_meta(self):
        """ Return a dict with all the meta of the tarfile
        """
        tarin = tarfile.open(self.filename, 'r' + self.compression)
        metadata = {}
        for item in tarin.getmembers():
            current_meta = {}
            if item.isfile():
                tarin.extract(item, self.tempdir)
                path = os.path.join(self.tempdir, item.name)
                from libmat.mat import create_class_file
                class_file = create_class_file(path, False, add2archive=self.add2archive)
                if class_file is not None:
                    meta = class_file.get_meta()
                    if meta:
                        current_meta['file'] = str(meta)
                else:
                    logging.info("%s's format is not supported or harmless", item.name)

                if not self.is_file_clean(item):  # if there is meta
                    current_meta['mtime'] = item.mtime
                    current_meta['uid'] = item.uid
                    current_meta['gid'] = item.gid
                    current_meta['uname'] = item.uname
                    current_meta['gname'] = item.gname
                    metadata[item.name] = str(current_meta)
        tarin.close()
        return metadata


class TerminalZipStripper(ZipStripper):
    """ Represent a terminal level archive.
        This type of archive can not contain nested archives.
        It is used for formats like docx, which are basically
        ziped xml.
    """
    pass


class GzipStripper(TarStripper):
    """ Represent a tar.gz archive
    """

    def __init__(self, filename, mime, backup, is_writable, **kwargs):
        super(GzipStripper, self).__init__(filename, mime, backup, is_writable, **kwargs)
        self.compression = ':gz'


class Bzip2Stripper(TarStripper):
    """ Represent a tar.bz2 archive
    """

    def __init__(self, filename, mime, backup, is_writable, **kwargs):
        super(Bzip2Stripper, self).__init__(filename, mime, backup, is_writable, **kwargs)
        self.compression = ':bz2'
