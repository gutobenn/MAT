""" Care about office's formats

"""

import logging
import os
import shutil
import tempfile
import xml.dom.minidom as minidom
import zipfile

try:
    import cairo
    import gi
    gi.require_version('Poppler', '0.18')
    from gi.repository import Poppler
except ImportError:
    logging.info('office.py loaded without PDF support')

import parser
import archive


class OpenDocumentStripper(archive.TerminalZipStripper):
    """ An open document file is a zip, with xml file into.
        The one that interest us is meta.xml
    """

    def get_meta(self):
        """ Return a dict with all the meta of the file by
            trying to read the meta.xml file.
        """
        metadata = super(OpenDocumentStripper, self).get_meta()
        zipin = zipfile.ZipFile(self.filename, 'r')
        try:
            content = zipin.read('meta.xml')
            dom1 = minidom.parseString(content)
            elements = dom1.getElementsByTagName('office:meta')
            for i in elements[0].childNodes:
                if i.tagName != 'meta:document-statistic':
                    nodename = ''.join(i.nodeName.split(':')[1:])
                    metadata[nodename] = ''.join([j.data for j in i.childNodes])
        except KeyError:  # no meta.xml file found
            logging.debug('%s has no opendocument metadata', self.filename)
        zipin.close()
        return metadata

    def remove_all(self):
        """ Removes metadata
        """
        return super(OpenDocumentStripper, self).remove_all(ending_blacklist=['meta.xml'])

    def is_clean(self):
        """ Check if the file is clean from harmful metadatas
        """
        clean_super = super(OpenDocumentStripper, self).is_clean()
        if clean_super is False:
            return False

        zipin = zipfile.ZipFile(self.filename, 'r')
        try:
            zipin.getinfo('meta.xml')
        except KeyError:  # no meta.xml in the file
            return True
        zipin.close()
        return False


class OpenXmlStripper(archive.TerminalZipStripper):
    """ Represent an office openxml document, which is like
        an opendocument format, with some tricky stuff added.
        It contains mostly xml, but can have media blobs, crap, ...
        (I don't like this format.)
    """

    def remove_all(self):
        """ Remove harmful metadata, by deleting everything that doesn't end with '.rels' in the
        'docProps' folder. """
        return super(OpenXmlStripper, self).remove_all(
            beginning_blacklist=['docProps/'], whitelist=['.rels'])

    def is_clean(self):
        """ Check if the file is clean from harmful metadatas.
            This implementation is faster than something like
            "return this.get_meta() == {}".
        """
        clean_super = super(OpenXmlStripper, self).is_clean()
        if clean_super is False:
            return False

        zipin = zipfile.ZipFile(self.filename)
        for item in zipin.namelist():
            if item.startswith('docProps/'):
                return False
        zipin.close()
        return True

    def get_meta(self):
        """ Return a dict with all the meta of the file
        """
        metadata = super(OpenXmlStripper, self).get_meta()

        zipin = zipfile.ZipFile(self.filename)
        for item in zipin.namelist():
            if item.startswith('docProps/'):
                metadata[item] = 'harmful content'
        zipin.close()
        return metadata


class PdfStripper(parser.GenericParser):
    """ Represent a PDF file
    """

    def __init__(self, filename, mime, backup, is_writable, **kwargs):
        super(PdfStripper, self).__init__(filename, mime, backup, is_writable, **kwargs)
        self.uri = 'file://' + os.path.abspath(self.filename)
        self.password = None
        try:
            self.pdf_quality = kwargs['low_pdf_quality']
        except KeyError:
            self.pdf_quality = False

        self.meta_list = frozenset(['title', 'author', 'subject',
                                    'keywords', 'creator', 'producer', 'metadata'])

    def is_clean(self):
        """ Check if the file is clean from harmful metadatas
        """
        document = Poppler.Document.new_from_file(self.uri, self.password)
        return not any(document.get_property(key) for key in self.meta_list)

    def remove_all(self):
        """ Opening the PDF with poppler, then doing a render
            on a cairo pdfsurface for each pages.

            http://cairographics.org/documentation/pycairo/2/

            The use of an intermediate tempfile is necessary because
            python-cairo segfaults on unicode.
            See http://bugs.debian.org/cgi-bin/bugreport.cgi?bug=699457
        """
        document = Poppler.Document.new_from_file(self.uri, self.password)
        try:
            output = tempfile.mkstemp()[1]

            # Size doesn't matter (pun intended),
            # since the surface will be resized before
            # being rendered
            surface = cairo.PDFSurface(output, 10, 10)
            context = cairo.Context(surface)  # context draws on the surface

            logging.debug('PDF rendering of %s', self.filename)
            for pagenum in range(document.get_n_pages()):
                page = document.get_page(pagenum)
                page_width, page_height = page.get_size()
                surface.set_size(page_width, page_height)
                context.save()
                if self.pdf_quality:  # this may reduce the produced PDF size
                    page.render(context)
                else:
                    page.render_for_printing(context)
                context.restore()
                context.show_page()  # draw context on surface
            surface.finish()
            shutil.move(output, self.output)
        except:
            logging.error('Something went wrong when cleaning %s.', self.filename)
            return False

        try:
            # For now, cairo cannot write meta, so we must use pdfrw
            # See the realted thread: http://lists.cairographics.org/archives/cairo/2007-September/011466.html
            import pdfrw

            logging.debug('Removing %s\'s superficial metadata', self.filename)
            trailer = pdfrw.PdfReader(self.output)
            trailer.Info.Producer = None
            trailer.Info.Creator = None
            writer = pdfrw.PdfWriter()
            writer.trailer = trailer
            writer.write(self.output)
            self.do_backup()
        except:
            logging.error('Unable to remove all metadata from %s, please install pdfrw', self.output)
            return False
        return True

    def get_meta(self):
        """ Return a dict with all the meta of the file
        """
        document = Poppler.Document.new_from_file(self.uri, self.password)
        metadata = {}
        for key in self.meta_list:
            if document.get_property(key):
                metadata[key] = document.get_property(key)
        return metadata
