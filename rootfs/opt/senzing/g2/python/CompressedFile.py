import csv
import gzip
import io
import json
from datetime import datetime


class G2UnsupportedFileTypeException(Exception):

    def __init__(self, *args, **kwargs):
        super().__init__(self, *args, **kwargs)


def peekLine(file_):

    pos = file_.tell()
    line = file_.readline()
    file_.seek(pos)

    return line


def getSuffix(str_):

    suffixIdx = str_.rfind('.')
    if suffixIdx == -1:
        return None

    return str_[suffixIdx:]


def isCompressedFile(filename_):

    suffix = getSuffix(filename_)

    return True if suffix and suffix.lower() in ('.gz', '.gzip', '.zip') else False


def openPossiblyCompressedFile(filename_, options_, encoding_='utf-8-sig'):

    suffix = getSuffix(filename_)

    if suffix and suffix.lower() == '.zip':
        raise G2UnsupportedFileTypeException('zip files are not currently supported, please use gzip')

    if suffix and suffix.lower() in ('.gz', '.gzip'):
        try:
            f = gzip.open(filename_, options_)
            # read the first line to make sure we can read this gzip file
            peekLine(f)
            return io.TextIOWrapper(io.BufferedReader(f), encoding=encoding_, errors='ignore')
        except IOError:
            # handle regular ZIP (non gzip) files later
            # if 'Not a gzipped file' in e.message:
            #     return zipfile.ZipFile(filename_, mode=options_)
            raise

    # not a compressed archive
    return io.open(filename_, options_, encoding=encoding_)


def removeQuoteChar(s):
    if len(s) > 1 and s[0] + s[-1] in ("''", '""'):
        return s[1:-1]
    return s


def fileRowParser(line, fileData, rowNum=0, errors_file=None, errors_short=False, errors_disable=False):

    def write_error(row_num, line, msg='ERROR: Unknown error'):
        ''' Write error to terminal and file if not disabled '''

        print(f'  ERROR: {msg} {row_num} ({line[:50]})', flush=True)

        if errors_file and not errors_disable:
            if not errors_short:
                errors_file.write(f'\n{str(datetime.now())} ERROR: {msg} {rowNum}\n\t{line}\n')
            else:
                errors_file.write(f'\n{str(datetime.now())} ERROR: {msg} {rowNum}\n')
            errors_file.flush()

    line = line.strip()

    if len(line) == 0:
        print(f'  WARNING: Row {rowNum} is blank')
        return None

    # Its a JSON string
    if fileData['FILE_FORMAT'] in ('JSON', 'JSONL'):
        try:
            rowData = json.loads(line)
        except Exception:
            write_error(rowNum, line, 'Invalid JSON in row')
            return None

        return rowData

    # Its a UMF string
    if fileData['FILE_FORMAT'] == 'UMF':
        if not (line.upper().startswith('<UMF_DOC') or not line.upper().endswith('/UMF_DOC>')):
            write_error(rowNum, line, 'Invalid UMF in row')
            return None

        return line

    # Its a CSV variant
    else:

        # --handling for multi-character delimiters as csv module does not allow for it
        try:
            if fileData['MULTICHAR_DELIMITER']:
                rowData = [removeQuoteChar(x.strip()) for x in line.split(fileData['DELIMITER'])]
            else:
                rowData = [removeQuoteChar(x.strip()) for x in next(csv.reader([line], delimiter=fileData['DELIMITER'], skipinitialspace=True))]

        except Exception:
            write_error(rowNum, line, 'Row could not be parsed')
            try:
                print(line)
            except Exception:
                pass
            return None

        if len(''.join(map(str, rowData)).strip()) == 0:
            print(f'  WARNING: Row {rowNum} is blank')
            return ''  # skip rows with no data
        if 'HEADER_ROW' in fileData:
            rowData = dict(zip(fileData['HEADER_ROW'], rowData))
        return rowData
