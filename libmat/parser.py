""" Parent class of all parser
"""

import os
import shutil
import tempfile


NOMETA = frozenset((
    '.bmp',   # "raw" image
    '.rdf',   # text
    '.txt',   # plain text
    '.xml',   # formatted text (XML)
    '.rels',  # openXML formatted text
))

FIELD = object()


class GenericParser(object):
    """ Parent class of all parsers
    """
    def __init__(self, filename, mime, backup, is_writable, **kwargs):
        self.filename = ''
        self.mime = mime
        self.backup = backup
        self.is_writable = is_writable
        self.filename = filename
        self.basename = os.path.basename(filename)
        self.output = tempfile.mkstemp()[1]

    def __del__(self):
        """ Remove tempfile if it was not used
        """
        if os.path.exists(self.output):
            from libmat.mat import secure_remove
            secure_remove(self.output)

    def get_meta(self):
        """ Return a key-value representation of the file's metadata.

        :ret dict key-value representation of the file's metadata.
        """
        raise NotImplementedError

    def is_clean(self):
        """
            Check if the file is clean from harmful metadatas
        """
        raise NotImplementedError

    def remove_all(self):
        """ Remove all compromising fields
        """
        raise NotImplementedError

    def create_backup_copy(self):
        """ Create a backup copy
        """
        shutil.copy2(self.filename, os.path.join(self.filename, '.bak'))

    def do_backup(self):
        """ Keep a backup of the file if asked.

            The process of double-renaming is not very elegant,
            but it greatly simplify new strippers implementation.
        """
        if self.backup:
            shutil.move(self.filename, os.path.join(self.filename, '.bak'))
        else:
            from libmat.mat import secure_remove
            secure_remove(self.filename)
        shutil.move(self.output, self.filename)
