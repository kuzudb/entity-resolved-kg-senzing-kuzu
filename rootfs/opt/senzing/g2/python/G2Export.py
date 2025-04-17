#! /usr/bin/env python3

import argparse
import contextlib
import csv
import gzip
import os
import pathlib
import subprocess
import sys
import textwrap
import time
from datetime import datetime

import G2Paths

from senzing import G2Engine, G2EngineFlags, G2Exception
from G2IniParams import G2IniParams


def print_error_msg(msg, error1, error2='', exit=False):
    """ Display error msg and optionally exit """

    print(textwrap.dedent(f'''\

                          ERROR: {msg}
                                 {error1}
                                 {error2}
                          '''), file=msg_output_handle)

    if exit:
        sys.exit(1)


def csv_fetch_next(handle, response, csv_header=None):
    """ Fetch next for CSV output """

    try:
        g2_engine.fetchNext(handle, response)
    except G2Exception as ex:
        print_error_msg('Could not fetch next export record', ex, exit=True)

    # If no csv_header is sent we fetched the header row initially. Decode, strip and split into list
    if not csv_header:
        return response.decode().strip().split(',')

    # Decode and check data doesn't exceed the csv field limit
    export_record = response.decode()
    if len(export_record) > csv.field_size_limit():
        csv.field_size_limit(int(len(export_record) * 1.5))
        print(f'    Increased CSV field limit size to: {csv.field_size_limit()}', file=msg_output_handle)
    export_record_dict = next(csv.DictReader([export_record], fieldnames=csv_header)) if export_record else None

    return export_record, export_record_dict


def json_fetch_next(handle, response):
    """ Fetch next for JSON output """

    try:
        g2_engine.fetchNext(handle, response)
    except G2Exception as ex:
        print_error_msg('Could not fetch next export record', ex, exit=True)

    return response.decode()


def do_stats_output(total_entity_count, start_time, batch_row_count):
    """ Print stats if output frequency interval and not disabled with -1. Reset batch row count if triggered """

    if args.outputFrequency != -1 and total_entity_count % args.outputFrequency == 0:
        time_now = datetime.now().strftime("%I:%M:%S %p").lower()
        rows_per_sec = int(float(batch_row_count) / (float(time.time() - start_time if time.time() - start_time != 0 else 1)))
        ents_per_sec = int(float(args.outputFrequency) / (float(time.time() - start_time if time.time() - start_time != 0 else 1)))
        print(f'  {total_entity_count:,} entities processed at {time_now} ({ents_per_sec:,} per second), {rows_per_sec:,} rows per second', file=msg_output_handle)

        start_time = time.time()
        batch_row_count = 0

    return start_time, batch_row_count


def csv_export():
    """ Export data in CSV format """

    fetched_rec_count = bad_count_outer = bad_count_inner = total_row_count = batch_row_count = entity_count = total_entity_count = 0

    # First row is header for CSV
    fetch_next_response = bytearray()
    csv_header = csv_fetch_next(export_handle, fetch_next_response)

    # Create writer object and write the header row
    try:
        writer = csv.DictWriter(output_file_handle, fieldnames=csv_header, dialect=csv.excel, quoting=csv.QUOTE_ALL)
        writer.writeheader()
    except csv.Error as ex:
        print_error_msg('Could not create CSV writer for output or write CSF header', ex, exit=True)

    start_time = time.time()

    # Read rows from the export handle
    export_record, export_record_dict = csv_fetch_next(export_handle, fetch_next_response, csv_header)

    while export_record:

        row_list = []
        fetched_rec_count += 1
        batch_row_count += 1

        # Bypass bad rows
        if 'RESOLVED_ENTITY_ID' not in export_record_dict:
            print_error_msg(f'RESOLVED_ENTITY_ID is missing at line: {fetched_rec_count}):', export_record.strip(), export_record_dict)
            (export_record, export_record_dict) = csv_fetch_next(export_handle, fetch_next_response, csv_header)
            bad_count_outer += 1
            fetched_rec_count += 1
            continue

        resolved_entity_id = export_record_dict['RESOLVED_ENTITY_ID']

        # Keep fetching all export rows for the current RES_ENT
        while export_record_dict and export_record_dict['RESOLVED_ENTITY_ID'] == resolved_entity_id:

            # Bypass bad rows
            if 'RECORD_ID' not in export_record_dict:
                print_error_msg(f'RECORD_ID is missing at line: {fetched_rec_count}):', export_record.strip(), export_record_dict)
                (export_record, export_record_dict) = csv_fetch_next(export_handle, fetch_next_response, csv_header)
                bad_count_inner += 1
                fetched_rec_count += 1
                continue

            # Strip leading symbols on match_key
            if export_record_dict['MATCH_KEY'] and export_record_dict['MATCH_KEY'][0:1] in ('+', '-'):
                export_record_dict['MATCH_KEY'] = export_record_dict['MATCH_KEY'][1:]

            # For CSV output with extended don't include JSON_DATA (unless -xcr is used)
            if args.extended and not args.extendCSVRelates and export_record_dict['RELATED_ENTITY_ID'] != '0':
                export_record_dict.pop('JSON_DATA', None)

            row_list.append(export_record_dict)
            (export_record, export_record_dict) = csv_fetch_next(export_handle, fetch_next_response, csv_header)
            fetched_rec_count += 1
            batch_row_count += 1

        entity_count += 1
        total_entity_count += 1

        # Write the rows for the entity
        try:
            writer.writerows(row_list)
        except Exception as ex:
            print_error_msg('Writing to CSV file', ex)
            return total_row_count, (bad_count_outer + bad_count_inner), 1
        total_row_count += len(row_list)

        (start_time, batch_row_count) = do_stats_output(total_entity_count, start_time, batch_row_count)

    return total_row_count, (bad_count_outer + bad_count_inner), 0


def json_export():
    """ Export data in JSON format """

    row_count = batch_row_count = 0
    start_time = time.time()

    fetch_next_response = bytearray()
    export_record = json_fetch_next(export_handle, fetch_next_response)

    while export_record:

        row_count += 1
        batch_row_count += 1

        try:
            output_file_handle.write(export_record)
        except IOError as ex:
            print_error_msg('Writing to JSON file', ex)
            return row_count, 0, 1

        start_time, batch_row_count = do_stats_output(row_count, start_time, batch_row_count)

        export_record = json_fetch_next(export_handle, fetch_next_response)

    return row_count, 0, 0


@contextlib.contextmanager
def open_file_stdout(file_name):
    """ Use with open context to open either a file od stdout """

    if file_name != '-':
        h = gzip.open(file_name, 'wt', compresslevel=args.compressFile) if args.compressFile else open(file_name, 'w')
    else:
        h = sys.stdout

    try:
        yield h
    finally:
        if h is not sys.stdout:
            h.close()


if __name__ == '__main__':

    # Filter options used in arg parse help for output filter and in final output information
    filter_levels = {
        0: 'All resolved records & all relationship levels',
        1: 'All entities, without any relationships',
        2: 'All entities, also include possible matches for each entity',
        3: 'All entities, also include relationships for each entity',
        4: 'All entities, also include name-only relationships for each entity',
        5: 'All entities, also include disclosed relationships for each entity'
    }

    g2export_parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter, allow_abbrev=False)
    g2export_parser.add_argument('-c', '--iniFile', dest='ini_file_name', default=None, nargs=1, help=textwrap.dedent('''\

                                                                                        Path and file name of optional G2Module.ini to use.

                                                                                        '''))
    g2export_parser.add_argument('-o', '--outputFile', required=True, nargs='+', help=textwrap.dedent('''\

                                                                                        Path and file name to send output to.

                                                                                        Use -o - to send to stdout. When using this option G2Export messages and
                                                                                        statistics are written to g2export.log.

                                                                                        '''))
    g2export_parser.add_argument('-f', '--outputFilter', default=0, type=int, choices=range(0, 6), help=textwrap.dedent(f'''\

                                                                                                            Specify only one value for the output filter - 0 through 5.

                                                                                                            Filter 0 requests all the match levels (1 through 5).

                                                                                                            Filters 2 through 5 include the prior filter values. For example, 3 would
                                                                                                            output all entities & possible matches & relationships.

                                                                                                                1 = {filter_levels[1]}
                                                                                                                2 = {filter_levels[2]}
                                                                                                                3 = {filter_levels[3]}
                                                                                                                4 = {filter_levels[4]}
                                                                                                                5 = {filter_levels[5]}

                                                                                                                Note: Filter 4 for name-only is for Senzing internal use.

                                                                                                            Default: %(default)s

                                                                                                            '''))
    g2export_parser.add_argument('-F', '--outputFormat', default='CSV', type=str.upper, choices=('CSV', 'JSON'), help=textwrap.dedent('''\

                                                                                                                        Data format to export to, JSON or CSV.

                                                                                                                        Default: %(default)s

                                                                                                                        '''))
    g2export_parser.add_argument('-x', '--extended', default=False, action="store_true", help=textwrap.dedent('''\

                                                                                                Return extended details, adds RESOLVED_ENTITY_NAME & JSON_DATA.

                                                                                                Adding JSON_DATA significantly increases the size of the output and execution time.

                                                                                                When used with CSV output, JSON_DATA isn\'t included for the related entities
                                                                                                (RELATED_ENTITY_ID) for each resolved entity (RESOLVED_ENTITY_ID). This reduces
                                                                                                the size of a CSV export by preventing repeating data for related entities. JSON_DATA
                                                                                                for the related entities is still included in the CSV export and is located in the
                                                                                                export record where the RELATED_ENTITY_ID = RESOLVED_ENTITY_ID.

                                                                                                WARNING: This is not recommended! To include the JSON_DATA for every CSV record see the
                                                                                                --extendCSVRelates (-xcr) argument.

                                                                                                '''))
    g2export_parser.add_argument('-of', '--outputFrequency', default=1000, type=int, help=textwrap.dedent('''\

                                                                                            Frequency of export output statistics.

                                                                                            Default: %(default)s

                                                                                            '''))
    g2export_parser.add_argument('-cf', '--compressFile', default=None, const=6, nargs='?', type=int, choices=range(1, 10), help=textwrap.dedent('''\

                                                                                                                                    Compress output file with gzip. Compression level can be optionally specified.

                                                                                                                                    If output file is specified as - (for stdout), use shell redirection instead to compress:
                                                                                                                                        G2Export.py -o - | gzip -v > myExport.csv.gz

                                                                                                                                    Default: %(const)s

                                                                                                                                    '''))
    g2export_parser.add_argument('-xcr', '--extendCSVRelates', default=False, action='store_true', help=textwrap.dedent('''\

                                                                                                            WARNING: Use of this argument is not recommended!

                                                                                                            Used in addition to --extend (-x), it will include JSON_DATA in CSV output for related entities.

                                                                                                            Only valid for CSV output format.

                                                                                                            '''))

    args = g2export_parser.parse_args()

    if args.outputFile[0] == '-' and args.compressFile:
        print('\nINFO: Output file is stdout (-o -), use shell redirection instead of --compressFile (-cf) to compress output.')
        sys.exit(0)

    # Open export or stdout, export stats and messages go to log file if export data is to stdout
    if args.outputFile[0] != '-':
        output_file_name = pathlib.Path(args.outputFile[0]).resolve()
        # Add .gz suffix if compressing
        output_file_name = output_file_name.with_suffix(output_file_name.suffix + '.gz') if args.compressFile else output_file_name
        msg_output_file = '-'
        warn_period = 10
    else:
        output_file_name = args.outputFile[0]
        msg_output_file = 'g2export.log'
        warn_period = 0

    # Open either log file or stdout for stats and messages
    with open_file_stdout(msg_output_file) as msg_output_handle:

        if args.extendCSVRelates and not args.extended:
            print(textwrap.dedent('''
                    ERROR: Argument --extendCSVRelates (-xcr) is used to complement --extended (-x) and not used alone.')

                           Review the help with G2Export.py --help
                '''), file=msg_output_handle)
            sys.exit(0)

        if args.extendCSVRelates:
            print(textwrap.dedent('''

                    ********** Warning **********

                    Using the --extendCSVRelates (-xcr) argument with CSV output format will result in excessive and
                    repeated data for related entities. Very rarely, if ever, is this option required!

                    Hit CTRL-C to exit or wait 10 seconds to continue.

                    Review the help with G2Export.py --help

                    *****************************
                    '''), file=msg_output_handle)

            time.sleep(warn_period)

        print(textwrap.dedent('''

                 ********** Warning **********

                 G2Export isn't intended for exporting large numbers of entities and associated data source record information.
                 Beyond 100M+ data source records isn't suggested. For exporting overview entity and relationship data for
                 analytical purposes outside of Senzing please review the following article:

                 https://senzing.zendesk.com/hc/en-us/articles/360010716274--Advanced-Replicating-the-Senzing-results-to-a-Data-Warehouse

                 *****************************
                 '''), file=msg_output_handle)

        time.sleep(warn_period / 2)

        exit_code = exportFlags = 0

        # Some CSV exports can be large especially with extended data. Is checked and increased in csv_fetch_next()
        csv.field_size_limit(300000)

        # Extended format (with ERRULE_CODE) hard coded to false for now. Applies to CSV output
        extendedFormat = False

        # Fields to use with CSV output, list of fields to request data
        # For CSV these are unioned with the data returned by the flags to give final output
        csvFields = ['RESOLVED_ENTITY_ID', 'RELATED_ENTITY_ID', 'MATCH_LEVEL', 'MATCH_KEY', 'DATA_SOURCE', 'RECORD_ID']
        if args.extended:
            csvFields.insert(2, 'RESOLVED_ENTITY_NAME')
            csvFields.insert(6, 'JSON_DATA')
        if extendedFormat:  # Hard coded to false for now
            csvFields.append('ERRULE_CODE')
        csvFields = ','.join(csvFields)

        # Check G2Project.ini isn't being used, now deprecated
        # Don't try and auto find G2Module.ini, safer to ask to be specified during this change!
        if args.ini_file_name and 'G2PROJECT.INI' in args.ini_file_name[0].upper():
            print('\nINFO: G2Export no longer uses G2Project.ini, it is deprecated and uses G2Module.ini instead.', file=msg_output_handle)
            print('      G2Export attempts to locate a default G2Module.ini (no -c) or use -c to specify path/name to your G2Module.ini', file=msg_output_handle)
            sys.exit(0)

    #Check if INI file or env var is specified, otherwise use default INI file
    ini_file_name = None

    if args.ini_file_name:
        ini_file_name = pathlib.Path(args.ini_file_name[0])
    elif os.getenv("SENZING_ENGINE_CONFIGURATION_JSON"):
        g2module_params = os.getenv("SENZING_ENGINE_CONFIGURATION_JSON")
    else:
        ini_file_name = pathlib.Path(G2Paths.get_G2Module_ini_path())

    if ini_file_name:
        G2Paths.check_file_exists_and_readable(ini_file_name)
        iniParamCreator = G2IniParams()
        g2module_params = iniParamCreator.getJsonINIParams(ini_file_name)

    # Initialise an engine
    try:
        print('\nStarting Senzing engine...', file=msg_output_handle)
        g2_engine = G2Engine()
        g2_engine.init('pyG2Export', g2module_params, False)
    except G2Exception as ex:
        print_error_msg(f'Error: Could not start the G2 engine using {ini_file_name}', ex, exit=True)

    # Determine data requested with engine flags
    exportFlags = G2EngineFlags.G2_EXPORT_INCLUDE_ALL_ENTITIES
    if args.outputFilter == 1:
        pass
    elif args.outputFilter == 2:
        exportFlags = exportFlags | G2EngineFlags.G2_EXPORT_INCLUDE_POSSIBLY_SAME | G2EngineFlags.G2_ENTITY_INCLUDE_POSSIBLY_SAME_RELATIONS
    elif args.outputFilter == 3:
        exportFlags = exportFlags | G2EngineFlags.G2_EXPORT_INCLUDE_POSSIBLY_SAME | G2EngineFlags.G2_EXPORT_INCLUDE_POSSIBLY_RELATED | G2EngineFlags.G2_ENTITY_INCLUDE_POSSIBLY_SAME_RELATIONS | G2EngineFlags.G2_ENTITY_INCLUDE_POSSIBLY_RELATED_RELATIONS
    elif args.outputFilter == 4:
        exportFlags = exportFlags | G2EngineFlags.G2_EXPORT_INCLUDE_POSSIBLY_SAME | G2EngineFlags.G2_EXPORT_INCLUDE_POSSIBLY_RELATED | G2EngineFlags.G2_EXPORT_INCLUDE_NAME_ONLY | G2EngineFlags.G2_ENTITY_INCLUDE_POSSIBLY_SAME_RELATIONS | G2EngineFlags.G2_ENTITY_INCLUDE_POSSIBLY_RELATED_RELATIONS | G2EngineFlags.G2_ENTITY_INCLUDE_NAME_ONLY_RELATIONS
    elif args.outputFilter >= 5:
        exportFlags = exportFlags | G2EngineFlags.G2_EXPORT_INCLUDE_POSSIBLY_SAME | G2EngineFlags.G2_EXPORT_INCLUDE_POSSIBLY_RELATED | G2EngineFlags.G2_EXPORT_INCLUDE_NAME_ONLY | G2EngineFlags.G2_EXPORT_INCLUDE_DISCLOSED | G2EngineFlags.G2_ENTITY_INCLUDE_ALL_RELATIONS
    else:
        exportFlags = exportFlags | G2EngineFlags.G2_ENTITY_INCLUDE_ALL_RELATIONS

    # if not extended:
    #  exportFlags |= g2_engine.G2_ENTITY_MINIMAL_FORMAT

    # Initialize the export
    print('\nExecuting export...', file=msg_output_handle)
    if args.outputFrequency == -1:
        print('\n\tExport statistics output was disabled.', file=msg_output_handle)

    export_start = time.time()

    # Open file or stdout for export output
    with open_file_stdout(output_file_name) as output_file_handle:

        # Create CSV or JSON export handle to fetch from
        try:
            if args.outputFormat == 'CSV':
                export_handle = g2_engine.exportCSVEntityReport(csvFields, exportFlags)
            else:
                # For JSON output amend the engine flags to obtain additional data
                # JSON output to match similar CSV output will include additional items, CSV unions flags & csvFields to determine output
                exportFlags = exportFlags | G2EngineFlags.G2_ENTITY_INCLUDE_RECORD_DATA | G2EngineFlags.G2_ENTITY_INCLUDE_RELATED_RECORD_DATA | G2EngineFlags.G2_ENTITY_INCLUDE_RECORD_MATCHING_INFO | G2EngineFlags.G2_ENTITY_INCLUDE_RELATED_MATCHING_INFO
                if args.extended:
                    # Note: There is no flag for JSON export to get the related JSON_DATA details to fully mimic CSV output
                    #       Would need to getRecord() and inject the JSON_DATA
                    exportFlags = exportFlags | G2EngineFlags.G2_ENTITY_INCLUDE_ENTITY_NAME | G2EngineFlags.G2_ENTITY_INCLUDE_RECORD_JSON_DATA
                export_handle = g2_engine.exportJSONEntityReport(exportFlags)
        except G2Exception as ex:
            print_error_msg('Could not initialize export', ex, exit=True)

        row_count, bad_rec_count, exit_code = csv_export() if args.outputFormat == 'CSV' else json_export()

    export_finish = time.time()

    # If compression requested try and collect stats from gunzip. If anything fails report on it in the final output
    if args.compressFile:
        try:
            process_output = subprocess.Popen(['gunzip', '--list', '--quiet', output_file_name], stdout=subprocess.PIPE, universal_newlines=True)
            stdout, _ = process_output.communicate()
            # Create a new list from the output, split and strip every element
            gunzip_details = [element.strip() for element in stdout.split()]
            size_compressed = int(gunzip_details[0]) / 1024 / 1024
            size_uncompressed = int(gunzip_details[1]) / 1024 / 1024
            comp_details = f'Level: {args.compressFile} - Compressed: {int(size_compressed)} MB - Uncompressed: {int(size_uncompressed)} MB - Ratio: {gunzip_details[2]}'
        except Exception as ex:
            comp_details = f'Collecting compression details failed: {ex}'

    # Display information for reference
    print(textwrap.dedent(f'''
                            Configuration parameters:    {ini_file_name if ini_file_name else 'Read from SENZING_ENGINE_CONFIGURATION_JSON env var'}
                            Export output file:          {output_file_name if output_file_name != '-' else 'stdout'}
                            Export output format:        {args.outputFormat}
                            Export filter level:         {args.outputFilter} - {filter_levels[args.outputFilter]}
                            Exported rows:               {row_count:,}
                            Bad rows skipped:            {bad_rec_count}
                            Start time:                  {datetime.fromtimestamp(export_start).strftime('%I:%M:%S%p').lower()}
                            End time:                    {datetime.fromtimestamp(export_finish).strftime('%I:%M:%S%p').lower()}
                            Execution time:              {round((export_finish - export_start) / 60, 1)} mins
                            Compression details:         {comp_details if args.compressFile else 'Compression not requested'}
                           '''), file=msg_output_handle)

    print('Export completed successfully.' if not exit_code else 'ERROR: Export did NOT complete successfully!', file=msg_output_handle)

    g2_engine.destroy()

    sys.exit(exit_code)
