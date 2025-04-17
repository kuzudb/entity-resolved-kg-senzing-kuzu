#! /usr/bin/env python3

import argparse
import importlib
import json
import math
import os
import pathlib
import select
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from contextlib import suppress
from datetime import datetime
from glob import glob
from multiprocessing import Process, Queue, Value, Manager
from queue import Empty, Full

import DumpStack
import G2Paths
from CompressedFile import fileRowParser, isCompressedFile, openPossiblyCompressedFile
from G2ConfigTables import G2ConfigTables
from G2IniParams import G2IniParams
from G2Project import G2Project

from senzing import G2Config, G2ConfigMgr, G2Diagnostic, G2Engine, G2Exception, G2Product, \
    G2LicenseException, G2NotFoundException

__all__ = []
__version__ = '2.2.6'  # See https://www.python.org/dev/peps/pep-0396/
__date__ = '2018-09-18'
__updated__ = '2023-12-14'

# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------


class UnconfiguredDataSourceException(Exception):

    def __init__(self, data_source_name):
        super().__init__(self, f"Datasource {data_source_name} not configured. See https://senzing.zendesk.com/hc/en-us/articles/360010784333 on how to configure data sources in the config file.")

# -----------------------------------------------------------------------------
# Class: Governor
#
# Dummy class for when no governor is imported
# -----------------------------------------------------------------------------


class Governor:

    def __init__(self, *args, **kwargs):
        return

    def govern(self, *args, **kwargs):
        """ Main function to trigger action(s) """
        return

# ---------------------------------------------------------------------
# G2Loader
# ---------------------------------------------------------------------


def check_resources_and_startup(return_queue, thread_count, do_purge):
    """ Check system resources, calculate a safe number of threads when argument not specified on command line """

    try:
        diag = G2Diagnostic()
        diag.init('pyG2Diagnostic', g2module_params, cli_args.debugTrace)
    except G2Exception as ex:
        print('\nERROR: Could not start G2Diagnostic for check_resources_and_startup()')
        print(f'       {ex}')
        return_queue.put(-1)
        return

    try:
        g2_engine = init_engine('pyG2StartSetup', g2module_params, cli_args.debugTrace, prime_engine=False)
    except G2Exception as ex:
        print('ERROR: Could not start the G2 engine for check_resources_and_startup()')
        print(f'       {ex}')
        return_queue.put(-1)
        return

    try:
        g2_configmgr = G2ConfigMgr()
        g2_configmgr.init('pyG2ConfigMgr', g2module_params, cli_args.debugTrace)
    except G2Exception as ex:
        print('ERROR: Could not start G2ConfigMgr for check_resources_and_startup()')
        print(f'       {ex}')
        return_queue.put(-1)
        return

    try:
        g2_product = G2Product()
        g2_product.init('pyG2LicenseVersion', g2module_params, cli_args.debugTrace)
    except G2Exception as ex:
        print('ERROR: Could not start G2Product for check_resources_and_startup()')
        print(f'       {ex}\n')
        return_queue.put(-1)
        return

    lic_info = json.loads(g2_product.license())
    ver_info = json.loads(g2_product.version())

    # Get the configuration list
    try:
        response = bytearray()
        g2_configmgr.getConfigList(response)
        config_list = json.loads(response.decode())
    except G2Exception as ex:
        print('ERROR: Could not get config list in check_resources_and_startup()')
        print(f'       {ex}')
        return_queue.put(-1)
        return

    # Get the active config ID
    try:
        response = bytearray()
        g2_engine.getActiveConfigID(response)
        active_cfg_id = int(response.decode())
    except G2Exception as ex:
        print('ERROR: Could not get the active config in check_resources_and_startup()')
        print(f'       {ex}')
        return_queue.put(-1)
        return

    # Get details for the currently active ID
    active_cfg_details = [details for details in config_list['CONFIGS'] if details['CONFIG_ID'] == active_cfg_id]
    config_comments = active_cfg_details[0]['CONFIG_COMMENTS']
    config_created = active_cfg_details[0]['SYS_CREATE_DT']

    # Get database info
    # {'Hybrid Mode': False, 'Database Details': [{'Name': '/home/ant/senzprojs/3.1.2.22182/var/sqlite/G2C.db', 'Type': 'sqlite3'}]}
    # {'Hybrid Mode': True, 'Database Details': [{'Name': '/home/ant/senzprojs/3.1.2.22182/var/sqlite/G2C.db', 'Type': 'sqlite3'}, {'Name': '/home/ant/senzprojs/3.1.2.22182/var/sqlite/G2C_LIB.db', 'Type': 'sqlite3'}, {'Name': '/home/ant/senzprojs/3.1.2.22182/var/sqlite/G2C_RES.db', 'Type': 'sqlite3'}]}
    # {'Hybrid Mode': False, 'Database Details': [{'Name': 'localhost', 'Type': 'postgresql'}]}
    # {'Hybrid Mode': True, 'Database Details': [{'Name': 'localhost', 'Type': 'postgresql'}]}

    try:
        response = bytearray()
        diag.getDBInfo(response)
        db_info = json.loads(response.decode())
    except G2Exception as ex:
        print('ERROR: Could not get the DB info in check_resources_and_startup()')
        print(f'       {ex}')
        return_queue.put(-1)
        return

    print(textwrap.dedent(f'''\n\
        Version & Config Details
        ------------------------

            Senzing Version:            {ver_info["VERSION"] + " (" + ver_info["BUILD_DATE"] + ")"  if "VERSION" in ver_info else ""}
            Configuration Parameters:   {ini_file_name if ini_file_name else 'Read from SENZING_ENGINE_CONFIGURATION_JSON env var'}
            Instance Config ID:         {active_cfg_id}
            Instance Config Comments:   {config_comments}
            Instance Config Created:    {config_created}
            Hybrid Database:            {'Yes' if db_info['Hybrid Mode'] else 'No'}
            Database(s):                '''), end='')

    for idx, db in enumerate(db_info['Database Details']):
        print(f'{" " * 32 if idx > 0 else ""}{db["Type"]} - {db["Name"]}')
        ini_db_types.append(db['Type'].upper())

    if len(set(ini_db_types)) != 1:
        print('\nERROR: No database detected in init parms or mixed databases in a hybrid setup!')
        print(f'       {ini_db_types}')
        return_queue.put(-1)
        return

    print(textwrap.dedent(f'''\n\
        License Details
        ---------------

            Customer:    {lic_info["customer"]}
            Type:        {lic_info["licenseType"]}
            Records:     {lic_info["recordLimit"]}
            Expiration:  {lic_info["expireDate"]}
            Contract:    {lic_info["contract"]}
     '''))

    physical_cores = diag.getPhysicalCores()
    logical_cores = diag.getLogicalCores()
    available_mem = diag.getAvailableMemory() / 1024 / 1024 / 1024.0
    total_mem = diag.getTotalSystemMemory() / 1024 / 1024 / 1024.0

    pause_msg = 'WARNING: Pausing for warning message(s)...'
    db_tune_article = 'https://senzing.zendesk.com/hc/en-us/articles/360016288254-Tuning-Your-Database'
    critical_error = warning_issued = False
    max_time_per_insert = 0.5

    #Limit the number of threads for sqlite, doesn't benefit from more and can slow down (6 is approx)
    max_sqlite_threads = 6
    sqlite_limit_msg = ''
    sqlite_warned = False

    # Obtain the default value to use for the max amount of memory to use
    calc_max_avail_mem = vars(g2load_parser)["_option_string_actions"]["-ntm"].const

    # Allow for higher factor when logical cores are available
    calc_cores_factor = 2 if physical_cores != logical_cores else 1.2

    print(textwrap.dedent(f'''\n\
        System Resources
        ----------------

            Physical cores:         {physical_cores}
            Logical cores:          {logical_cores if physical_cores != logical_cores else ''}
            Total memory (GB):      {total_mem:.1f}
            Available memory (GB):  {available_mem:.1f}
        '''))

    if not cli_args.thread_count:

        # Allow for 1 GB / thread
        thread_calc_from_mem = math.ceil(available_mem / 100 * calc_max_avail_mem)
        possible_num_threads = math.ceil(physical_cores * calc_cores_factor)

        # Are the number of safe calculated threads <= 80% of available mem
        if possible_num_threads <= thread_calc_from_mem:
            thread_count = possible_num_threads
            calc_thread_msg = '- Using maximum calculated number of threads. This can likely be increased if there is no database running locally.'
        # Else if the thread_calc_from_mem (num of threads of 80% mem) is greater than the number of physical cores use that many threads
        elif thread_calc_from_mem >= physical_cores:
            thread_count = thread_calc_from_mem
            calc_thread_msg = '- Additional processing capability is available, but not enough memory to safely support a higher thread count.'
        # Low available memory compared to physical cores x factor, set to use half safe calculated memory value
        else:
            thread_count = math.ceil(thread_calc_from_mem / 2)
            calc_thread_msg = f'- WARNING: System has less than 1 GB {(thread_calc_from_mem / physical_cores):.2f} GB available per physical core.\n \
                            Number of threads will be significantly reduced, you may see further warnings and should check your resources.'

        # If a value was specified for -ntm override the thread count with the min of calc value or possible_num_threads
        thread_count = min(math.ceil(available_mem / 100 * cli_args.threadCountMem), possible_num_threads) if cli_args.threadCountMem else thread_count
        mem_percent = calc_max_avail_mem if not cli_args.threadCountMem else cli_args.threadCountMem
        mem_msg = 'available' if not cli_args.threadCountMem else 'requested (-ntm)'
        calc_thread_msg = calc_thread_msg if not cli_args.threadCountMem else ''

        # Don't reformat and move end ''')), it's neater to do this than try and move cursor for next optional calc_thread_msg
        print(textwrap.dedent(f'''
            Number of threads
            -----------------

                - Number of threads arg (-nt) not specified. Calculating number of threads using {mem_percent}% of {mem_msg} memory.
                - Monitor system resources. Use command line argument -nt to increase (or decrease) the number of threads on subsequent use.'''))

        # Add extra message if args.threadCountMem wasn't specified
        if calc_thread_msg:
            print(f'    {calc_thread_msg}')
        print()

    # Limit number of threads when sqlite, unless -nt arg specified
    if 'SQLITE3' in ini_db_types:
        if cli_args.thread_count:
            thread_count = cli_args.thread_count
            if thread_count > max_sqlite_threads:
                sqlite_limit_msg = f' - WARNING: Greater than {max_sqlite_threads} could be slower when using SQLite'
                sqlite_warned = True
        else:
            thread_count = min(thread_count, max_sqlite_threads)
            sqlite_limit_msg = f' - Default is {max_sqlite_threads} when using SQLite, test higher/lower with -nt argument'

    # 2.5GB per process - .5GB per thread
    min_recommend_cores = math.ceil(thread_count / 4 + 1)
    num_processes = math.ceil(float(thread_count) / cli_args.max_threads_per_process)
    min_recommend_mem = (num_processes * 2.5 + thread_count * .5)

    print(textwrap.dedent(f'''\n\
        Resources Requested
        -------------------

            Number of threads:           {thread_count} {sqlite_limit_msg}
            Threads calculated:          {'Yes' if not cli_args.thread_count else 'No, -nt argument was specified'}
            Threads per process:         {cli_args.max_threads_per_process}
            Number of processes:         {num_processes}
            Min recommended cores:       {min_recommend_cores}
            Min recommended memory (GB): {min_recommend_mem:.1f}
        '''))

    if sqlite_warned:
        print(pause_msg, flush=True)
        time.sleep(10)

    # Skip perf check if specified on CLI args or container env var
    if not cli_args.skipDBPerf and not env_var_skip_dbperf:
        print(textwrap.dedent('''\n\
            Database Performance
            --------------------
            '''))

        db_perf_response = bytearray()
        diag.checkDBPerf(3, db_perf_response)
        perf_info = json.loads(db_perf_response.decode())

        num_recs_inserted = perf_info.get('numRecordsInserted', None)
        if num_recs_inserted:
            insert_time = perf_info['insertTime']
            time_per_insert = (1.0 * insert_time / num_recs_inserted) if num_recs_inserted > 0 else 999
            print(textwrap.indent(textwrap.dedent(f'''\
                Records inserted:    {num_recs_inserted:,}
                Period for inserts:  {insert_time} ms
                Average per insert:  {time_per_insert:.1f} ms
            '''), '    '))
        else:
            print('\nERROR: Database performance tests failed!\n')

        if time_per_insert > max_time_per_insert:
            warning_issued = True
            print(textwrap.dedent(f'''\
                WARNING: Database performance of {time_per_insert:.1f} ms per insert is slower than the recommended minimum of {max_time_per_insert:.1f} ms per insert
                         For database tuning please refer to: {db_tune_article}
            '''))

    if physical_cores < min_recommend_cores:
        warning_issued = True
        print(f'WARNING: System has fewer ({physical_cores}) than the minimum recommended cores ({min_recommend_cores}) for this configuration\n')

    if min_recommend_mem > available_mem:
        critical_error = True
        print(f'!!!!! CRITICAL WARNING: SYSTEM HAS LESS MEMORY AVAILABLE ({available_mem:.1f} GB) THAN THE MINIMUM RECOMMENDED ({min_recommend_mem:.1f} GB) !!!!!\n')

    if critical_error or warning_issued:
        print(pause_msg, flush=True)
        time.sleep(10 if critical_error else 3)

    # Purge repository
    if do_purge:
        print('\nPurging Senzing database...')
        g2_engine.purgeRepository(False)

    # Clean up (in reverse order of initialization)
    g2_product.destroy()
    del g2_product

    g2_configmgr.destroy()
    del g2_configmgr

    g2_engine.destroy()
    del g2_engine

    diag.destroy()
    del diag

    # Return values are put in a queue
    return_queue.put(thread_count)


def perform_load():
    """ Main processing when not in redo only mode """

    exit_code = 0
    DumpStack.listen()
    proc_start_time = time.time()

    # Prepare the G2 configuration
    g2_config_json = bytearray()
    temp_queue = Queue()
    get_initial_g2_config_process = Process(target=get_initial_g2_config_process_wrapper, args=(temp_queue, g2module_params, g2_config_json))
    get_initial_g2_config_process.start()
    g2_config_json = temp_queue.get(block=True)
    result_of_get_initial_g2_config = temp_queue.get(block=True)
    get_initial_g2_config_process.join()

    if not result_of_get_initial_g2_config:
        return 1, 0

    g2_config_tables = G2ConfigTables(g2_config_json)

    g2_project = G2Project(g2_config_tables, dsrcAction, cli_args.projectFileName, cli_args.projectFileSpec, cli_args.tmpPath)
    if not g2_project.success:
        return 1, 0

    # Enhance the G2 configuration, by adding data sources and entity types
    if not cli_args.testMode:
        temp_queue = Queue()
        enhance_g2_config_process = Process(target=enhance_g2_config_process_wrapper, args=(temp_queue, g2_project, g2module_params, g2_config_json, cli_args.configuredDatasourcesOnly))
        enhance_g2_config_process.start()
        g2_config_json = temp_queue.get(block=True)
        result_of_enhance_g2_config = temp_queue.get(block=True)
        enhance_g2_config_process.join()
        if not result_of_enhance_g2_config:
            return 1, 0

    # Start loading
    for sourceDict in g2_project.sourceList:

        file_path = sourceDict['FILE_PATH']
        orig_file_path = file_path
        shuf_detected = False

        cnt_rows = cnt_bad_parse = cnt_bad_umf = cnt_good_umf = api_errors.value = 0
        dsrc_action_add_count.value = dsrc_action_del_count.value = dsrc_action_reeval_count.value = 0

        g2_project.clearStatPack()

        if cli_args.testMode:
            print(f'\nTesting {file_path}, CTRL-C to end test at any time...\n')
        else:
            if dsrcAction == 'D':
                print(f'\n{"-"*30}  Deleting  {"-"*30}\n')
            elif dsrcAction == 'X':
                print(f'\n{"-"*30}  Reevaluating  {"-"*30}\n')
            else:
                print(f'\n{"-"*30}  Loading  {"-"*30}\n')

        # Drop to a single thread for files under 500k
        if os.path.getsize(file_path) < (100000 if isCompressedFile(file_path) else 500000):
            print('  Dropping to single thread due to small file size')
            transport_thread_count = 1
        else:
            transport_thread_count = default_thread_count

        # Shuffle the source file for performance, unless directed not to or in test mode or single threaded
        if not cli_args.noShuffle and not cli_args.testMode and transport_thread_count > 1:

            if isCompressedFile(file_path):
                print('INFO: Not shuffling compressed file. Please ensure the data was shuffled before compressing!\n')

            # If it looks like source file was previously shuffled by G2Loader don't do it again
            elif SHUF_NO_DEL_TAG in file_path or SHUF_TAG in file_path:

                shuf_detected = True
                print(f'INFO: Not shuffling source file, previously shuffled. {SHUF_TAG} or {SHUF_NO_DEL_TAG} in file name\n')
                if SHUF_NO_DEL_TAG in file_path and cli_args.shuffleNoDelete:
                    print(f'INFO: Source files with {SHUF_NO_DEL_TAG} in the name are not deleted by G2Loader. Argument -snd (--shuffleNoDelete) used\n')
                time.sleep(10)

            else:

                # Add timestamp to no delete shuffled files
                shuf_file_suffix = SHUF_NO_DEL_TAG + datetime.now().strftime("%Y%m%d_%H-%M-%S") if cli_args.shuffleNoDelete else SHUF_TAG
                plib_file_path = pathlib.Path(file_path).resolve()
                shuf_file_path = pathlib.Path(str(plib_file_path) + shuf_file_suffix)

                # Look for previously shuffled files in original path...
                if not cli_args.shuffFilesIgnore:

                    prior_shuf_files = [str(pathlib.Path(p).resolve()) for p in glob(file_path + SHUF_TAG_GLOB)]

                    # ...and  shuffle redirect path if specified
                    if cli_args.shuffFileRedirect:
                        redirect_glob = str(shuf_path_redirect.joinpath(plib_file_path.name)) + SHUF_TAG_GLOB
                        prior_shuf_files.extend([str(pathlib.Path(p).resolve()) for p in glob(redirect_glob)])

                    if prior_shuf_files:
                        print(f'\nFound previously shuffled files matching {plib_file_path.name}...\n')

                        prior_shuf_files.sort()
                        for psf in prior_shuf_files:
                            print(f'  {psf}')

                        print(textwrap.dedent(f'''
                            Pausing for {SHUF_RESPONSE_TIMEOUT} seconds... (This check can be skipped with the command line argument --shuffFilesIgnore (-sfi) )

                            The above listed files may not contain the same data as the input file.
                            If you wish to use one of the above, please check and compare the files to ensure the previously shuffled file is what you expect.

                            To quit and use a previously shuffled file hit <Enter>. To continue, wait {SHUF_RESPONSE_TIMEOUT} seconds or type c and <Enter>
                        '''))

                        # Wait 30 seconds to allow user to use a prior shuffle, timeout and continue if automated
                        while True:
                            r, _, _ = select.select([sys.stdin], [], [], SHUF_RESPONSE_TIMEOUT)
                            if r:
                                # Read without hitting enter?
                                read_input = sys.stdin.readline()
                                if read_input == '\n':
                                    sys.exit(0)
                                elif read_input.lower() == 'c\n':
                                    break
                                else:
                                    print('<Enter> to quit or type c and <Enter> to continue: ')
                            else:
                                break

                else:
                    print(f'INFO: Skipping check for previously shuffled files for {plib_file_path.name}')

                # If redirecting the shuffled file modify to redirect path
                if cli_args.shuffFileRedirect:
                    shuf_file_path = shuf_path_redirect.joinpath(shuf_file_path.name)

                print(f'\nShuffling file to: {shuf_file_path}\n')

                cmd = f'shuf {file_path} > {shuf_file_path}'
                if sourceDict['FILE_FORMAT'] not in ('JSON', 'UMF'):
                    cmd = f'head -n1 {file_path} > {shuf_file_path} && tail -n+2 {file_path} | shuf >> {shuf_file_path}'

                try:
                    process = subprocess.run(cmd, shell=True, check=True)
                except subprocess.CalledProcessError as ex:
                    print(f'\nERROR: Shuffle command failed: {ex}')
                    return 1, 0

                file_path = str(shuf_file_path)

        file_reader = openPossiblyCompressedFile(file_path, 'r')
        # --file_reader = safe_csv_reader(csv.reader(csvFile, fileFormat), cnt_bad_parse)

        # Use previously stored header row, so get rid of this one
        if sourceDict['FILE_FORMAT'] not in ('JSON', 'UMF'):
            next(file_reader)

        # Start processes and threads for this file
        thread_list, work_queue = start_loader_process_and_threads(transport_thread_count)

        if thread_stop.value != 0:
            return exit_code, 0

        # Start processing rows from source file
        file_start_time = time.time()
        batch_start_time = time.perf_counter()

        cnt_rows = batch_time_governing = time_redo.value = time_governing.value = dsrc_action_diff.value = 0

        while True:

            try:
                row = next(file_reader)
            except StopIteration:
                break
            except Exception as ex:
                cnt_rows += 1
                cnt_bad_parse += 1
                print(f'WARNING: Could not read row {cnt_rows}, {ex}')
                continue

            # Increment row count to agree with line count and references to bad rows are correct
            cnt_rows += 1

            # Skip records
            if not cli_args.redoMode and cli_args.skipRecords and cnt_rows < cli_args.skipRecords + 1:
                if cnt_rows == 1:
                    print(f'INFO: Skipping the first {cli_args.skipRecords} records...')
                continue

            # Skip blank or records that error, errors written to errors file if not disabled
            row_data = fileRowParser(row, sourceDict, cnt_rows, errors_file=errors_file, errors_short=cli_args.errorsShort, errors_disable=cli_args.errorsFileDisable)
            if not row_data:
                cnt_bad_parse += 1
                continue

            # Don't do any transformation if this is raw UMF
            ok_to_continue = True
            if sourceDict['FILE_FORMAT'] != 'UMF':

                # Update with file defaults
                if 'DATA_SOURCE' not in row_data and 'DATA_SOURCE' in sourceDict:
                    row_data['DATA_SOURCE'] = sourceDict['DATA_SOURCE']

                if cli_args.testMode:
                    mapping_response = g2_project.testJsonRecord(row_data, cnt_rows, sourceDict)
                    if mapping_response[0]:
                        cnt_bad_umf += 1
                        ok_to_continue = False

                # --only add force a load_id if not in test mode (why do we do this??)
                if 'LOAD_ID' not in row_data:
                    row_data['LOAD_ID'] = sourceDict['FILE_NAME']

            # Put the record on the queue
            if ok_to_continue:
                cnt_good_umf += 1
                if not cli_args.testMode:
                    while True:
                        try:
                            # Assist in indicating what type of record this is for processing thread
                            # Detect and set here if dsrc action was set as reeval on args
                            work_queue.put((row_data, True if dsrcAction == 'X' else False), True, 1)
                        except Full:
                            # Check to see if any threads have died
                            if not all((thread.is_alive() for thread in thread_list)):
                                print(textwrap.dedent('''\n\
                                    ERROR: Thread(s) have shutdown unexpectedly!

                                           - This typically happens when memory resources are exhausted and the system randomly kills processes.

                                           - Please review: https://senzing.zendesk.com/hc/en-us/articles/115000856453

                                           - Check output from the following command for out of memory messages.

                                                - dmesg -e
                                '''))
                                return 1, cnt_bad_parse
                            continue
                        break

            if cnt_rows % cli_args.loadOutputFrequency == 0:
                batch_speed = int(cli_args.loadOutputFrequency / (time.perf_counter() - (batch_start_time - batch_time_governing))) if time.perf_counter() - batch_start_time != 0 else 1
                print(f'  {cnt_rows:,} rows processed at {time_now()}, {batch_speed:,} records per second{f", {api_errors.value:,} API errors" if api_errors.value > 0 else ""}', flush=True)

                batch_start_time = time.perf_counter()
                batch_time_governing = 0

            # Process redo during ingestion
            if cnt_rows % cli_args.redoInterruptFrequency == 0 and not cli_args.testMode and not cli_args.noRedo:
                if process_redo(work_queue, True, 'Waiting for processing queue to empty to start redo...'):
                    print('\nERROR: Could not process redo record!\n')

            # Check to see if any threads threw errors or control-c pressed and shut down
            if thread_stop.value != 0:
                exit_code = thread_stop.value
                break

            # Check if any of the threads died without throwing errors
            if not all((thread.is_alive() for thread in thread_list)):
                print('\nERROR: Thread failure!')
                break

            # Governor called for each record
            # Called here instead of when reading from queue to allow queue to act as a small buffer
            try:
                rec_gov_start = time.perf_counter()
                record_governor.govern()
                rec_gov_stop = time.perf_counter()
                with time_governing.get_lock():
                    time_governing.value += (rec_gov_stop - rec_gov_start)
                batch_time_governing += rec_gov_stop - rec_gov_start
            except Exception as err:
                shutdown(f'\nERROR: Calling per record governor: {err}')

            # Break this file if stop on record value
            if not cli_args.redoMode and cli_args.stopOnRecord and cnt_rows >= cli_args.stopOnRecord:
                print(f'\nINFO: Stopping at record {cnt_rows}, --stopOnRecord (-sr) argument was set')
                break

        # Process redo at end of processing a source. Wait for queue to empty of ingest records first
        if thread_stop.value == 0 and not cli_args.testMode and not cli_args.noRedo:
            if process_redo(work_queue, True, 'Source file processed, waiting for processing queue to empty to start redo...'):
                print('\nERROR: Could not process redo record!\n')

        end_time = time.time()
        end_time_str = time_now(True)

        # Close input file
        file_reader.close()

        if sourceDict['FILE_SOURCE'] == 'S3':
            print(" Removing temporary file created by S3 download " + file_path)
            os.remove(file_path)

        # Remove shuffled file unless run with -snd or prior shuffle detected and not small file/low thread count
        if not cli_args.shuffleNoDelete \
           and not shuf_detected \
           and not cli_args.noShuffle \
           and not cli_args.testMode \
           and transport_thread_count > 1:
            with suppress(Exception):
                print(f'\nDeleting shuffled file: {shuf_file_path}')
                os.remove(shuf_file_path)

        # Stop processes and threads
        stop_loader_process_and_threads(thread_list, work_queue)

        # Print load stats if not error or ctrl-c
        if exit_code in (0, 9):
            processing_secs = end_time - file_start_time
            elapsed_secs = time.time() - file_start_time
            elapsed_mins = round(elapsed_secs / 60, 1)

            # Calculate approximate transactions/sec, remove timings that aren't part of ingest
            file_tps = int((cnt_good_umf + cnt_bad_parse + cnt_bad_umf) / (processing_secs - time_governing.value - time_starting_engines.value - time_redo.value)) if processing_secs > 0 else 0

            # Use good records count instead of 0 on small fast files
            file_tps = file_tps if file_tps > 0 else cnt_good_umf

            if shuf_detected:
                shuf_msg = 'Shuffling skipped, file was previously shuffled by G2Loader'
            elif transport_thread_count > 1:
                if cli_args.noShuffle:
                    shuf_msg = 'Not shuffled (-ns was specified)'
                else:
                    shuf_msg = shuf_file_path if cli_args.shuffleNoDelete and 'shuf_file_path' in locals() else 'Shuffled file deleted (-snd to keep after load)'
            else:
                shuf_msg = 'File wasn\'t shuffled, small size or number of threads was 1'

            # Format with separator if specified
            skip_records = f'{cli_args.skipRecords:,}' if cli_args.skipRecords and cli_args.skipRecords != 0 else ''
            stop_on_record = f'{cli_args.stopOnRecord:,}' if cli_args.stopOnRecord and cli_args.stopOnRecord != 0 else ''

            # Set error log file to blank or disabled msg if no errors or arg disabled it
            errors_log_file = errors_file.name if errors_file else ''

            if not api_errors.value and not cnt_bad_parse:
                errors_log_file = 'No errors'

            if cli_args.errorsFileDisable:
                errors_log_file = 'Disabled with -ed'

            rec_dsrc_action = dsrc_action_add_count.value + dsrc_action_del_count.value + dsrc_action_reeval_count.value if dsrc_action_diff.value else 0
            if dsrcAction != 'A':
                rec_dsrc_action = f'Not considered, explicit mode specified ({dsrc_action_names[dsrcAction]})'

            rec_dsrc_action = rec_dsrc_action if isinstance(rec_dsrc_action, str) else f'{rec_dsrc_action:,}'

            print(textwrap.dedent(f'''\n\
                    Processing Information
                    ----------------------

                        Arguments:                       {" ".join(sys.argv[1:])}
                        Action:                          {dsrc_action_names[dsrcAction]}
                        Repository purged:               {'Yes' if (cli_args.purgeFirst or cli_args.forcePurge) else 'No'}
                        Source File:                     {pathlib.Path(orig_file_path).resolve()}
                        Shuffled into:                   {shuf_msg}
                        Total records:                   {cnt_good_umf + cnt_bad_parse + cnt_bad_umf:,}
                        \tGood records:                {cnt_good_umf:,}
                        \tBad records:                 {cnt_bad_parse:,}
                        \tIncomplete records:          {cnt_bad_umf:,}
                        Records specifying action:       {rec_dsrc_action}
                        \tAdds:                        {dsrc_action_add_count.value:,}
                        \tDeletes:                     {dsrc_action_del_count.value:,}
                        \tReeval:                      {dsrc_action_reeval_count.value:,}
                        Errors:
                        \tErrors log file:             {errors_log_file}
                        \tFailed API calls:            {api_errors.value:,}
                        Skipped records:                 {skip_records + ' (-skr was specified)' if cli_args.skipRecords else 'Not requested'}
                        Stop on record:                  {stop_on_record + ' (-sr was specified)' if cli_args.stopOnRecord else 'Not requested'}
                        Total elapsed time:              {elapsed_mins} mins
                        \tStart time:                  {datetime.fromtimestamp(file_start_time).strftime('%I:%M:%S%p').lower()}
                        \tEnd time:                    {end_time_str}
                        \tTime processing redo:        {str(round(time_redo.value / 60, 1)) + ' mins' if not cli_args.testMode and not cli_args.noRedo else 'Redo disabled (-n)'}
                        \tTime paused in governor(s):  {round(time_governing.value / 60, 1)} mins
                        Records per second:              {file_tps:,}
                '''))

        # Don't process next source file if errors
        if exit_code:
            break

    elapsed_mins = round((time.time() - proc_start_time) / 60, 1)

    if exit_code:
        print(f'\nProcess aborted at {time_now()} after {elapsed_mins} minutes')
    else:
        print(f'\nProcess completed successfully at {time_now()} in {elapsed_mins} minutes')
        if cli_args.noRedo:
            print(textwrap.dedent(f'''\n

                    Process Redo Records
                    --------------------

                    Loading is complete but the processing of redo records was disabled with --noRedo (-n).

                    All source records have been entity resolved, there may be minor clean up of some entities
                    required. Please review: https://senzing.zendesk.com/hc/en-us/articles/360007475133

                    If redo records are not being processed separately by another G2Loader instance in redo only
                    mode - or another process you've built to manage redo records - run G2Loader again in redo
                    only mode:

                        ./G2Loader.py --redoMode {"--iniFile " + str(ini_file_name) if ini_file_name else ""}
                    '''))

    if cli_args.testMode:

        report = g2_project.getTestResults('F')
        report += '\nPress (s)ave to file or (q)uit when reviewing is complete\n'

        less = subprocess.Popen(["less", "-FMXSR"], stdin=subprocess.PIPE)

        # Less returns BrokenPipe if hitting q to exit earlier than end of report
        try:
            less.stdin.write(report.encode('utf-8'))
        except IOError:
            pass

        less.stdin.close()
        less.wait()

    # Governor called for each source
    try:
        source_governor.govern()
    except Exception as err:
        shutdown(f'\nERROR: Calling per source governor: {err}')

    return exit_code, cnt_bad_parse


def start_loader_process_and_threads(transport_thread_count):

    thread_list = []
    work_queue = None

    # Start transport threads, bypass if in test mode
    if not cli_args.testMode:

        thread_stop.value = 0
        work_queue = Queue(transport_thread_count * 10)
        num_threads_left = transport_thread_count
        thread_id = 0

        while num_threads_left > 0:
            thread_id += 1
            thread_list.append(Process(target=send_to_g2, args=(thread_id, work_queue, min(cli_args.max_threads_per_process, num_threads_left), cli_args.debugTrace, thread_stop, cli_args.noWorkloadStats, dsrcAction)))
            num_threads_left -= cli_args.max_threads_per_process

        for thread in thread_list:
            thread.start()

    return thread_list, work_queue


def send_to_g2(thread_id_, work_queue_, num_threads_, debug_trace, thread_stop, no_workload_stats, dsrc_action):

    g2_engines = []

    try:
        g2_engine = init_engine(f'pyG2Engine{thread_id_}', g2module_params, debug_trace, prime_engine=True, add_start_time=True)
        g2_engines.append(g2_engine)
    except G2Exception as ex:
        print('ERROR: Could not start the G2 engine for sendToG2()')
        print(f'       {ex}')

        with thread_stop.get_lock():
            thread_stop.value = 1
        return

    try:

        thread_list = []

        for myid in range(num_threads_):
            thread_list.append(threading.Thread(target=g2_thread, args=(f'{thread_id_}-{myid}', work_queue_, g2_engine, thread_stop, dsrc_action)))

        for thread in thread_list:
            thread.start()

        # Periodically output engine workload stats
        if not no_workload_stats:
            break_stop = False

            while thread_stop.value == 0:

                start_time = time.time()
                while (time.time() - start_time) <= cli_args.workloadOutputFrequency:
                    # Check if stopping between sleeping, set break_stop to prevent workload stats
                    if thread_stop.value != 0:
                        break_stop = True
                        break

                    # Sleep in small period, don't sleep the full amount or can block StopLoaderAndThreads() finishing
                    time.sleep(2)

                if break_stop:
                    break

                for engine in g2_engines:
                    dump_workload_stats(engine)

        for thread in thread_list:
            thread.join()

    except Exception:
        with thread_stop.get_lock():
            thread_stop.value = 1
        pass

    # Final workload stats as finishing up
    if not no_workload_stats:
        dump_workload_stats(g2_engine)

    with suppress(Exception):
        g2_engine.destroy()
        del g2_engine

    return


def g2_thread(_, work_queue_, g2_engine_, thread_stop, dsrc_action_args):
    """ g2 thread function """

    def g2thread_error(msg, action):
        """ Write out errors during processing """

        call_error = textwrap.dedent(f'''
            {str(datetime.now())} ERROR: {action} - {msg}
                Data source: {data_source}
                Record ID: {record_id}
                Record Type: {"Redo" if is_redo_record else "Ingest"}

                {row if not cli_args.errorsShort else " "}
           ''')

        # If logging to error file is disabled print instead
        if cli_args.errorsFileDisable:
            print(call_error, flush=True, end='\033[F\033[F' if cli_args.errorsShort else '\n')

        if not cli_args.errorsFileDisable:
            try:
                errors_file.write(f'\n\n{call_error.strip()}')
                errors_file.flush()
            except Exception as ex:
                print(f'\nWARNING: Unable to write API error to {errors_file.name}')
                print(f'         {ex}', flush=True)
                # If can't write to file, write to terminal
                print(call_error, flush=True, end='\033[F\033[F' if cli_args.errorsShort else '\n')

        # Increment value to report at end of processing each source
        with api_errors.get_lock():
            api_errors.value += 1

    # For each work queue item
    while thread_stop.value == 0 or work_queue_.empty() is False:

        try:
            row = work_queue_.get(True, 1)
        except Empty:
            row = None
            continue

        # Unpack tuple from the work queue into the data and indicator for being a redo record
        row, is_redo_record = row

        dsrc_action_str = None

        # Start with dsrc_action set to what was used as the CLI arg or default of add
        dsrc_action = dsrc_action_args

        # Record is JSON
        data_source = row.get('DATA_SOURCE', '')
        record_id = str(row.get('RECORD_ID', ''))

        # Is the record from the work queue specifically a redo record to be processed during redo time/mode?
        if is_redo_record:
            dsrc_action = 'X'

        # If not, it's a normal ingestion record from file or project
        else:
            # If -D and -X were not specified, check each record for dsrc_action and use it instead of default add mode
            # Consideration of dsrc_action is only valid in default add mode
            if not cli_args.deleteMode and not cli_args.reprocessMode:

                # Use the DSRC_ACTION from inbound row?
                # Check if the inbound row specifies dsrc_action, use it and override CLI args (X, D, default is A) if present
                # This provides functionality of sending in input file with multiple dsrc actions
                row_dsrc_action = row.get('DSRC_ACTION', None)
                dsrc_action = row_dsrc_action if row_dsrc_action else dsrc_action
                dsrc_action = dsrc_action.upper() if isinstance(dsrc_action, str) else dsrc_action

                # If the row dsrc_action differs from the CLI ARGs dsrc_action mode, log the fact to print info at end of data source
                if dsrc_action != dsrc_action_args:
                    # Not enabled, could quickly fill up redirected logging files
                    if dsrc_action_diff.value != 1:
                        with dsrc_action_diff.get_lock():
                            dsrc_action_diff.value = 1

                    if dsrc_action == 'A':
                        with dsrc_action_add_count.get_lock():
                            dsrc_action_add_count.value += 1

                    if dsrc_action == 'D':
                        with dsrc_action_del_count.get_lock():
                            dsrc_action_del_count.value += 1

                    if dsrc_action == 'X':
                        with dsrc_action_reeval_count.get_lock():
                            dsrc_action_reeval_count.value += 1

        try:
            # Catch invalid dsrc_actions and push to error log and log as an API error
            if dsrc_action not in ("A", "D", "X"):
                g2thread_error('Unknown dsrc_action', dsrc_action)
                continue

            if dsrc_action == 'A':
                dsrc_action_str = 'addRecord()'
                g2_engine_.addRecord(data_source, record_id, json.dumps(row, sort_keys=True))

            if dsrc_action == 'D':
                dsrc_action_str = 'deleteRecord()'
                g2_engine_.deleteRecord(data_source, record_id)

            if dsrc_action == 'X':
                dsrc_action_str = 'reevaluateRecord()'
                # Check if the redo record is a REPAIR_ENTITY one, call reevaluateEntity() if so
                # {'UMF_PROC': {'NAME': 'REPAIR_ENTITY', 'PARAMS': [{'PARAM': {'NAME': 'ENTITY_ID', 'VALUE': '32705738'}}]}}
                if not data_source and not record_id:
                    entity_id = row.get("UMF_PROC", {}).get("PARAMS", {})[0].get("PARAM", {}).get("VALUE", None)
                    if entity_id:
                        g2_engine_.reevaluateEntity(entity_id)
                    else:
                        g2thread_error("Unable to process redo record format!", dsrc_action_str)
                else:
                    g2_engine_.reevaluateRecord(data_source, record_id, 0)

        except G2LicenseException as ex:
            print('\nERROR: G2Engine licensing error!')
            print(f'       {ex}')
            with thread_stop.get_lock():
                thread_stop.value = 1
            return
        except G2NotFoundException as ex:
            # Don't error if record for redo can't be located
            if is_redo_record:
                pass
            else:
                g2thread_error(ex, dsrc_action_str)
        except G2Exception as ex:
            g2thread_error(ex, dsrc_action_str)


def stop_loader_process_and_threads(thread_list, work_queue):

    if not cli_args.testMode:

        print()

        # It is possible to reach here and the processes be shut down. This can happen when using PostgreSQL and the
        # Governor is paused waiting for a vacuum and CTRL-C is sent. Thus, ensure there are processes/threads alive
        # or the while will never exit
        while work_queue.empty() is False and any((thread.is_alive() for thread in thread_list)):
            print(f'Waiting for remaining records on the queue to be read, remaining: {work_queue.qsize()}', flush=True)
            time.sleep(2)

        with thread_stop.get_lock():
            thread_stop.value = 1

        print('Waiting for processing threads to finish...\n', flush=True)
        for thread in thread_list:
            thread.join()

        work_queue.close()


def dump_workload_stats(engine):
    """ Print JSON workload stats """

    response = bytearray()
    engine.stats(response)

    print(f'\n{json.dumps(json.loads(response.decode()))}\n', flush=True)


def init_engine(name, config_parms, debug_trace, prime_engine=True, add_start_time=False):
    """  Initialize an engine. add_start_time is for redo engines only """

    if add_start_time:
        engine_start_time = time.perf_counter()

    try:
        engine = G2Engine()
        engine.init(name, config_parms, debug_trace)
        if prime_engine:
            engine.primeEngine()
    except G2Exception:
        raise

    if add_start_time:
        with time_starting_engines.get_lock():
            time_starting_engines.value += (time.perf_counter() - engine_start_time)

    return engine


def process_redo(q, empty_q_wait=False, empty_q_msg='', sleep_interval=1):
    """ Called in normal and redo only mode (-R) to process redo records that need re-evaluation """

    # Drain the processing queue of ingest records before starting to process redo
    if empty_q_wait:
        print(f'\n{empty_q_msg}') if empty_q_msg else print('', end='')
        while not q.empty():
            time.sleep(sleep_interval)

    # This may look weird but ctypes/ffi have problems with the native code and fork.
    setup_process = Process(target=redo_feed, args=(q, cli_args.debugTrace, cli_args.redoMode, cli_args.redoModeInterval))

    redo_start_time = time.perf_counter()

    setup_process.start()
    setup_process.join()

    with time_redo.get_lock():
        time_redo.value += (time.perf_counter() - redo_start_time)

    return setup_process.exitcode


def redo_feed(q, debug_trace, redo_mode, redo_mode_interval):
    """ Process records in the redo queue """

    pass_num = cnt_rows = batch_time_governing = 0
    batch_start_time = time.time()
    rec_bytes = bytearray()
    rec = None
    test_get_redo = False

    try:
        redo_engine = init_engine('pyG2Redo', g2module_params, debug_trace, prime_engine=False, add_start_time=False)

        # Only do initial count if in redo mode, counting large redo can be expensive
        if redo_mode:
            redo_count = redo_engine.countRedoRecords()
            print(f'Redo records: {redo_count:,}')

        # Test if there is anything on redo queue
        else:
            try:
                redo_engine.getRedoRecord(rec_bytes)
                rec = rec_bytes.decode()
                test_get_redo = True
            except G2Exception as ex:
                print('ERROR: Could not get redo record for redoFeed()')
                print(f'       {ex}')
                exit(1)

    except G2Exception as ex:
        print('ERROR: Could not start the G2 engine for redoFeed()')
        print(f'       {ex}')
        exit(1)

    # If test didn't return a redo record, exit early
    if not rec and not redo_mode:
        print('\n  No redo to perform, resuming loading...\n')
        return

    # Init redo governor in this process, trying to use DB connection in forked process created outside will cause errors when using
    # PostgreSQL governor such as: psycopg2.OperationalError: SSL error: decryption failed or bad record mac
    redo_governor = Governor()
    if governor:
        redo_governor = governor.Governor(thread_stop, type='Redo per redo record', g2module_params=g2module_params, frequency='record', pre_post_msgs=False)

    if not redo_mode:
        print('\n  Pausing loading to process redo records...')

    while thread_stop.value == 0:

        # Don't get another redo record if fetched one during test of redo queue
        if not test_get_redo:
            try:
                redo_engine.getRedoRecord(rec_bytes)
                rec = rec_bytes.decode()
            except G2Exception as ex:
                print('ERROR: Could not get redo record for redoFeed()')
                print(f'       {ex}')
                exit(1)

        test_get_redo = False

        if not rec:
            pass_num += 1
            if pass_num > 10:
                if redo_mode:
                    print(f'  Redo queue empty, {cnt_rows:,} total records processed. Waiting {redo_mode_interval} seconds for next cycle at {time_now(True)} (CTRL-C to quit)...')
                    # Sleep in 1 second increments to respond to user input
                    for x in range(1, redo_mode_interval):
                        if thread_stop.value == 9:
                            break
                        time.sleep(1.0)
                else:
                    break
            time.sleep(0.05)
            continue
        else:
            pass_num = 0

        cnt_rows += 1

        while True:
            try:
                # Tuple to indicate if a record on work queue is redo - (rec, True == this is redo)
                q.put((json.loads(rec), True), True, 1)
            except Full:
                if thread_stop.value != 0:
                    break
                continue
            break

        if cnt_rows % cli_args.loadOutputFrequency == 0:
            redo_speed = int(cli_args.loadOutputFrequency / (time.time() - batch_start_time - batch_time_governing)) if time.time() - batch_start_time != 0 else 1
            print(f'  {cnt_rows:,} redo records processed at {time_now()}, {redo_speed:,} records per second')
            batch_start_time = time.time()
            batch_time_governing = 0

        # Governor called for each redo record
        try:
            redo_gov_start = time.perf_counter()
            redo_governor.govern()
            redo_gov_stop = time.perf_counter()
            time_governing.value += (redo_gov_stop - redo_gov_start)
            batch_time_governing += (redo_gov_stop - redo_gov_start)
        except Exception as ex:
            shutdown(f'\nERROR: Calling per redo governor: {ex}')

    if cnt_rows > 0:
        print(f'\t{cnt_rows:,} reevaluations completed\n')

    redo_engine.destroy()
    del redo_engine

    if not redo_mode:
        print('  Redo processing complete resuming loading...\n')

    return


def load_redo_queue_and_process():

    exit_code = 0
    DumpStack.listen()
    proc_start_time = time.time()

    thread_list, work_queue = start_loader_process_and_threads(default_thread_count)
    if thread_stop.value != 0:
        return exit_code

    if thread_stop.value == 0 and not cli_args.testMode and not cli_args.noRedo:
        exit_code = process_redo(work_queue)

    stop_loader_process_and_threads(thread_list, work_queue)

    elapsed_mins = round((time.time() - proc_start_time) / 60, 1)
    if exit_code:
        print(f'\nRedo processing cycle aborted after {elapsed_mins} minutes')
    else:
        print(f'\nRedo processing cycle completed successfully in {elapsed_mins} minutes')

    return exit_code


def addDataSource(g2_config_module, config_doc, data_source, configured_datasources_only):
    """ Adds a data source if does not exist """

    return_code = 0  # 1=inserted, 2=updated

    config_handle = g2_config_module.load(config_doc)
    dsrc_exists = False
    dsrc_list_doc_string = bytearray()
    g2_config_module.listDataSources(config_handle, dsrc_list_doc_string)
    dsrc_list_doc = json.loads(dsrc_list_doc_string.decode())
    dsrc_list_node = dsrc_list_doc['DATA_SOURCES']

    for dsrcNode in dsrc_list_node:
        if dsrcNode['DSRC_CODE'].upper() == data_source:
            dsrc_exists = True

    if dsrc_exists is False:
        if configured_datasources_only is False:
            add_data_source_json = '{\"DSRC_CODE\":\"%s\"}' % data_source
            add_data_source_result_buf = bytearray()
            g2_config_module.addDataSource(config_handle, add_data_source_json, add_data_source_result_buf)
            new_config = bytearray()
            g2_config_module.save(config_handle, new_config)
            config_doc[::] = b''
            config_doc += new_config
            return_code = 1
        else:
            raise UnconfiguredDataSourceException(data_source)

    g2_config_module.close(config_handle)

    return return_code


def get_initial_g2_config_process_wrapper(return_queue, params, g2_config_json):
    result = get_initial_g2_config(params, g2_config_json)
    # Return values are put in a queue
    return_queue.put(g2_config_json)
    return_queue.put(result)


def get_initial_g2_config(params, g2_config_json):

    # Get the current configuration from the database
    g2_config_mgr = G2ConfigMgr()
    g2_config_mgr.init('g2ConfigMgr', params, False)
    default_config_id = bytearray()
    g2_config_mgr.getDefaultConfigID(default_config_id)

    if len(default_config_id) == 0:
        print('ERROR: No default config stored in database. (see https://senzing.zendesk.com/hc/en-us/articles/360036587313)')
        return False
    default_config_doc = bytearray()
    g2_config_mgr.getConfig(default_config_id, default_config_doc)

    if len(default_config_doc) == 0:
        print('ERROR: No default config stored in database. (see https://senzing.zendesk.com/hc/en-us/articles/360036587313)')
        return False
    g2_config_json[::] = b''
    g2_config_json += default_config_doc
    g2_config_mgr.destroy()
    del g2_config_mgr

    return True


def enhance_g2_config_process_wrapper(return_queue, g2_project, params, g2_config_json, configured_datasources_only):
    result = enhance_g2_config(g2_project, params, g2_config_json, configured_datasources_only)
    # Return values are put in a queue
    return_queue.put(g2_config_json)
    return_queue.put(result)


def enhance_g2_config(g2_project, params, g2_config_json, configured_datasources_only):

    # Define variables for where the config is stored.

    g2_config = G2Config()
    g2_config.init("g2Config", params, False)

    # Add any missing source codes and entity types to the g2 config
    g2_new_config_required = False
    for sourceDict in g2_project.sourceList:
        if 'DATA_SOURCE' in sourceDict:
            try:
                if addDataSource(g2_config, g2_config_json, sourceDict['DATA_SOURCE'], configured_datasources_only) == 1:  # inserted
                    g2_new_config_required = True
            except UnconfiguredDataSourceException as err:
                print(err)
                return False

    # Add a new config, if we made changes
    if g2_new_config_required is True:
        g2_config_mgr = G2ConfigMgr()
        g2_config_mgr.init("g2ConfigMgr", params, False)
        new_config_id = bytearray()

        try:
            g2_config_mgr.addConfig(g2_config_json.decode(), 'Updated From G2Loader', new_config_id)
        except G2Exception:
            print("Error: Failed to add new config to the datastore")
            return False

        try:
            g2_config_mgr.setDefaultConfigID(new_config_id)
        except G2Exception:
            print("Error: Failed to set new config as default")
            return False
        g2_config_mgr.destroy()
        del g2_config_mgr

    g2_config.destroy()
    del g2_config

    return True


def time_now(add_secs=False):
    """ Date time now for processing messages """

    fmt_string = '%I:%M%p'
    if add_secs:
        fmt_string = '%I:%M:%S%p'

    return datetime.now().strftime(fmt_string).lower()


def signal_int(sig, frame):
    """ Signal interrupt handler """

    shutdown(f'USER INTERRUPT ({sig}) - Stopping threads, please be patient this can take a number of minutes...')


def shutdown(msg=None):
    """ Shutdown threads and exit cleanly from Governor if in use and clean up Governor """

    if msg:
        print(f'{msg}')

    print('Shutting down...\n')

    with thread_stop.get_lock():
        thread_stop.value = 9

    return


def governor_setup():
    """ Import and create governors """

    # Create default governors, replace if using a real governor for PostgreSQL
    rec_governor = Governor()
    src_governor = Governor()

    # When Postgres always import the Postgres governor - unless requested disabled (e.g., getting started and no native driver)
    if not cli_args.governor and 'POSTGRESQL' in ini_db_types and not cli_args.governorDisable:
        print(f'\nUsing PostgreSQL, loading default governor: {DEFAULT_POSTGRES_GOVERNOR}\n')
        import_governor = DEFAULT_POSTGRES_GOVERNOR[:-3] if DEFAULT_POSTGRES_GOVERNOR.endswith('.py') else DEFAULT_POSTGRES_GOVERNOR
    # If a governor was specified import it
    elif cli_args.governor:
        import_governor = cli_args.governor[0][:-3] if cli_args.governor[0].endswith('.py') else cli_args.governor[0]
        print(f'\nLoading governor {import_governor}\n')
    # Otherwise use dummy governors
    else:
        return rec_governor, src_governor, False

    try:
        gov = importlib.import_module(import_governor)
    except ImportError as ex:
        print(f'\nERROR: Unable to import governor {import_governor}')
        print(f'       {ex}')
        sys.exit(1)

    # If not in redo mode create all governors we may call upon
    if not cli_args.redoMode:

        # Init governors for each record, each source. Governor creation sets defaults, can override. See sample governor-postgresXID.py
        # Minimum keyword args: g2module_params, frequency
        # Example of overriding governor init parms
        # rec_governor = governor.Governor(type='Ingest per source record', g2module_params=g2module_params, frequency='record', wait_time=20, resume_age=5000, xid_age=1500000)
        rec_governor = gov.Governor(thread_stop, type='Ingest per source record', g2module_params=g2module_params, frequency='record')
        src_governor = gov.Governor(thread_stop, type='Ingest per source', g2module_params=g2module_params, frequency='source')

    # If in redo mode only create a redo governor
    if cli_args.redoMode or not cli_args.noRedo:
        # Redo governor created and destroyed here only to produce startup output, real redo governor is created in redo process
        gov.Governor(thread_stop, type='Redo per redo record', g2module_params=g2module_params, frequency='record')

    return rec_governor, src_governor, gov


if __name__ == '__main__':

    DEFAULT_POSTGRES_GOVERNOR = 'governor_postgres_xid.py'
    SHUF_NO_DEL_TAG = '_-_SzShufNoDel_-_'
    SHUF_TAG = '_-_SzShuf_-_'
    SHUF_TAG_GLOB = '_-_SzShuf*'
    SHUF_RESPONSE_TIMEOUT = 30

    exit_code = 0

    thread_stop = Value('i', 0)
    time_starting_engines = Value('d', 0)
    time_governing = Value('d', 0)
    time_redo = Value('d', 0)
    api_errors = Value('i', 0)
    dsrc_action_diff = Value('i', 0)

    # Human friendly names
    dsrc_action_names = {"A": "Add",
                         "D": "Delete",
                         "X": "Reevaluate"
                         }

    # Counts for records using different dsrc action
    dsrc_action_add_count = Value('i', 0)
    dsrc_action_del_count = Value('i', 0)
    dsrc_action_reeval_count = Value('i', 0)

    manager = Manager()
    ini_db_types = manager.list()

    signal.signal(signal.SIGINT, signal_int)
    signal.signal(signal.SIGTERM, signal_int)
    DumpStack.listen()

    tmp_path = os.path.join(tempfile.gettempdir(), 'senzing', 'g2')

    # Set default path for errors file to current path of script to start, modify if can find a suitable var path
    errors_file_name = f'g2loader_errors.{str(datetime.now().strftime("%Y%m%d_%H%M%S"))}'
    errors_file_default = pathlib.Path(__file__).parent.resolve().joinpath(errors_file_name)

    senz_root = os.environ.get('SENZING_ROOT', None)
    sys_senz_var = pathlib.Path('/var/opt/senzing')

    # SENZING_ROOT is available on bare metal
    if senz_root:
        errors_file_default = pathlib.Path(senz_root) / 'var' / errors_file_name

    # In containers /var/opt/senzing should be available
    elif sys_senz_var.exists() and sys_senz_var.is_dir():
        errors_file_default = pathlib.Path(sys_senz_var) / errors_file_name

    # Don't allow argparse to create abbreviations of options
    g2load_parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter, allow_abbrev=False)
    g2load_parser.add_argument('-c', '--iniFile', default=None, metavar='file', nargs=1,
                               help=textwrap.dedent('''\

                                      Path and name of optional G2Module.ini file to use.

                                    '''))

    # Both -p and -f shouldn't be used together
    file_project_group = g2load_parser.add_mutually_exclusive_group()
    file_project_group.add_argument('-p', '--projectFile', default=None, dest='projectFileName', metavar='file',
                                    help=textwrap.dedent('''\

                                           Path and name of a project CSV or JSON file.

                                    '''))

    file_project_group.add_argument('-f', '--fileSpec', default=[], dest='projectFileSpec', metavar='file', nargs='+',
                                    help=textwrap.dedent('''\

                                           Path and name of a source file to load, such as /data/mydata.json

                                           Optional parameters, generally these should not be required:

                                               /data/mydata/?data_source=TEST
                                               /data/mydata/?data_source=TEST,file_format=PIPE

                                               data_source = The data source to apply to each record in the file
                                               file_format = If not detected use one of: JSON, CSV, TAB, TSV, PIPE

                                               Note: A data_source specified here will not override the data_source specified in a record.
                                                     It is recommended to be explicit and specify data_source in the source file records.

                                    '''))

    g2load_parser.add_argument('-T', '--testMode', action='store_true', default=False,
                               help=textwrap.dedent('''\

                                      Run in test mode and collect stats without loading, CTRL-C anytime to exit early.

                                    '''))

    g2load_parser.add_argument('-X', '--reprocess', action='store_true', default=False, dest='reprocessMode',
                               help=textwrap.dedent('''\

                                      Force reprocessing of previously loaded file.

                                    '''))

    g2load_parser.add_argument('-t', '--debugTrace', action='store_true', default=False,
                               help=textwrap.dedent('''\

                                      Output debug trace information.

                                    '''))

    g2load_parser.add_argument('-nw', '--noWorkloadStats', action='store_true',
                               help=textwrap.dedent('''\

                                      Disable workload statistics information.

                                    '''))

    g2load_parser.add_argument('-n', '--noRedo', action='store_true', default=False,
                               help=textwrap.dedent('''\

                                      Disable redo processing.

                                      Another instance of G2Loader can be run in redo only mode or redo can be processed after ingestion.

                                    '''))

    g2load_parser.add_argument('-i', '--redoModeInterval', default=60, metavar='seconds', type=int,
                               help=textwrap.dedent('''\

                                      Time in secs to wait between redo processing checks, only used in redo mode.

                                      Default: %(default)s

                                    '''))

    g2load_parser.add_argument('-k', '--knownDatasourcesOnly', action='store_true', default=False, dest='configuredDatasourcesOnly',
                               help=textwrap.dedent('''\

                                      Only accepts configured and known data sources.

                               '''))

    g2load_parser.add_argument('-mtp', '--maxThreadsPerProcess', default=64, dest='max_threads_per_process', metavar='num_threads', type=int,
                               help=textwrap.dedent('''\

                                      Maximum threads per process.

                                      Default: %(default)s

                                    '''))

    g2load_parser.add_argument('-g', '--governor', default=None, metavar='file', nargs=1,
                               help=textwrap.dedent(f'''\

                                       User supplied governor to load and call during processing, used for PostgreSQL databases.

                                       Default: {DEFAULT_POSTGRES_GOVERNOR}

                                     '''))

    g2load_parser.add_argument('-gd', '--governorDisable', action='store_true', default=False,
                               help=textwrap.dedent('''\

                                      Disable the Postgres governor.

                              '''))

    g2load_parser.add_argument('-tmp', '--tmpPath', default=tmp_path, metavar='path', nargs='?',
                               help=textwrap.dedent(f'''\

                                      Path to use instead of {tmp_path} (For S3 files).

                               '''))

    g2load_parser.add_argument('-skr', '--skipRecords', default=0, metavar='num_recs', type=int,
                               help=textwrap.dedent('''\

                                      Skip the first n records in a file.

                                    '''))

    g2load_parser.add_argument('-sfi', '--shuffFilesIgnore', action='store_true', default=False,
                               help=textwrap.dedent('''\

                                      Skip checking for previously shuffled files to use, and prompting to use them.

                                    '''))

    g2load_parser.add_argument('-sfr', '--shuffFileRedirect', default=None, metavar='path', nargs='+',
                               help=textwrap.dedent('''\

                                      Alternative path to output shuffled file to, useful for performance and device space.

                                      Default: Same path as original file.

                                    '''))

    # Both -ef and -ed shouldn't be used together
    g2load_parser.add_argument('-es', '--errorsShort', action='store_true', default=False,
                               help=textwrap.dedent('''\

                                      Reduce size of the errors file by not including the record.

                                    '''))

    error_file_group = g2load_parser.add_mutually_exclusive_group()
    error_file_group.add_argument('-ef', '--errorsFile', default=errors_file_default, metavar='file', nargs='?',
                                  help=textwrap.dedent('''\

                                         Path/file to write errors to.

                                         Default: %(default)s

                                       '''))

    error_file_group.add_argument('-efd', '--errorsFileDisable', action='store_true', default=False,
                                  help=textwrap.dedent('''\

                                         Turn off writing errors to file, written to terminal instead.

                                       '''))

    # Both -nt and -ntm shouldn't be used together
    num_threads_group = g2load_parser.add_mutually_exclusive_group()
    num_threads_group.add_argument('-nt', '--threadCount', default=0, dest='thread_count', metavar='num_threads', type=int,
                                   help=textwrap.dedent('''\

                                          Total number of threads to start.

                                          Default: Calculated based on hardware

                                        '''))

    num_threads_group.add_argument('-ntm', '--threadCountMem', choices=range(10, 81), const=80, default=None, metavar='10 -> 80', nargs='?', type=int,
                                   help=textwrap.dedent('''\

                                          Percentage of memory to use when calculating threads (when -nt not specified).

                                          Default: %(const)s

                                   '''))

    # Both -ns and -snd shouldn't be used together
    no_shuf_shuf_no_del = g2load_parser.add_mutually_exclusive_group()
    no_shuf_shuf_no_del.add_argument('-ns', '--noShuffle', action='store_true', default=False,
                                     help=textwrap.dedent('''\

                                            Don\'t shuffle input file(s).

                                            Shuffling improves performance and shouldn\'t be disabled unless pre-shuffled.

                                     '''))

    no_shuf_shuf_no_del.add_argument('-snd', '--shuffleNoDelete', action='store_true', default=False,
                                     help=textwrap.dedent(f'''\

                                            Don\'t delete shuffled source file(s) after G2Loader shuffles them.

                                            Adds {SHUF_NO_DEL_TAG} and timestamp to the shuffled file. G2Loader can detect and reuse shuffled files.

                                     '''))

    # Both -R and -sr shouldn't be used together
    stop_row_redo_node = g2load_parser.add_mutually_exclusive_group()
    stop_row_redo_node.add_argument('-R', '--redoMode', action='store_true', default=False,
                                    help=textwrap.dedent('''\

                                           Run in redo only mode, processes the redo queue.

                                    '''))

    stop_row_redo_node.add_argument('-sr', '--stopOnRecord', default=0, metavar='num_recs', type=int,
                                    help=textwrap.dedent('''\

                                           Stop processing after n records (for testing large files).

                                    '''))

    # Both -P and -D shouldn't be used together
    purge_dsrc_delete = g2load_parser.add_mutually_exclusive_group()
    purge_dsrc_delete.add_argument('-D', '--delete', action='store_true', default=False, dest='deleteMode',
                                   help=textwrap.dedent('''\

                                          Force deletion of a previously loaded file.

                                   '''))

    purge_dsrc_delete.add_argument('-P', '--purgeFirst', action='store_true', default=False,
                                   help=textwrap.dedent('''\

                                          Purge the Senzing repository before loading, confirmation prompt before purging.

                                          WARNING: This will remove all ingested data and outcomes from the Senzing repository!
                                                   Only use if you wish to start with a clean Senzing system before loading.
                                                   If you are unsure please contact support@senzing.com

                                   '''))

    purge_dsrc_delete.add_argument('--FORCEPURGE', action='store_true', default=False, dest='forcePurge',
                                   help=textwrap.dedent('''\

                                          Purge the Senzing repository before loading, NO confirmation prompt before purging.

                                          WARNING: This will remove all ingested data and outcomes from the Senzing repository!
                                                   Only use if you wish to start with a clean Senzing system before loading.
                                                   If you are unsure please contact support@senzing.com

                                   '''))

    # Options hidden from help, used for testing
    # Frequency to output load and redo rate
    g2load_parser.add_argument('-lof', '--loadOutputFrequency', default=1000, type=int, help=argparse.SUPPRESS)

    # Frequency to output workload stats - default is 2 mins
    g2load_parser.add_argument('-wof', '--workloadOutputFrequency', default=120, type=int, help=argparse.SUPPRESS)

    # Frequency to pause loading and perform redo
    g2load_parser.add_argument('-rif', '--redoInterruptFrequency', default=100000, type=int, help=argparse.SUPPRESS)

    # Disable DB Perf
    g2load_parser.add_argument('-sdbp', '--skipDBPerf', action='store_true', default=False, help=argparse.SUPPRESS)

    cli_args = g2load_parser.parse_args()

    if len(sys.argv) < 2:
        print(f'\n{g2load_parser.format_help()}')
        sys.exit(0)

    print(textwrap.dedent('''
            ***************************************************************************************************************
            *                                                                                                             *
            * G2Loader is a sample batch utility to accelerate getting started with Senzing and ingesting data in Proof   *
            * of Concept (PoC) scenarios. G2Loader is a supported utility for PoCs, but is not supported for production   *
            * use.                                                                                                        *
            *                                                                                                             *
            * Senzing is a library providing entity resolution APIs. These APIs are to be utilized by your own            *
            * applications, process and systems. G2Loader is a demonstrable application using some of the ingestion APIs. *
            *                                                                                                             *
            * Typically, the Senzing APIs are embedded in and called by streaming systems to provide real time entity     *
            * resolution capabilities. Example of a streaming ingest utility: https://github.com/senzing-garage/stream-   *
            * loader                                                                                                      *
            *                                                                                                             *
            ***************************************************************************************************************
            '''))
    time.sleep(1)

    # Check env vars that may be needed to react to, e.g. set in infrastructure such as Senzing containers
    check_skip_dbperf = os.environ.get("SENZING_SKIP_DATABASE_PERFORMANCE_TEST", "UNSET")
    env_var_skip_dbperf = True if check_skip_dbperf != "UNSET" and check_skip_dbperf == 'true' else False

    sshd_warning = os.environ.get("SENZING_SSHD_SHOW_PERFORMANCE_WARNING", "UNSET")
    if sshd_warning != "UNSET" and sshd_warning == 'true':
        print(textwrap.dedent('''
            ********** WARNING **********

            It looks like you are trying to run G2Loader in a resource limited container.

            G2Loader in this environment will not perform or scale, it's acceptable to use for small tests.

            For appropriate ingestion infrastructure please check:

                https://github.com/senzing-garage/stream-producer
                https://github.com/senzing-garage/stream-loader

            *****************************
            '''))
        time.sleep(5)

    # Check for additional mutually exclusive arg combinations not easy to cover in argparse and sensible values
    if (cli_args.purgeFirst or cli_args.forcePurge) and cli_args.redoMode:
        print('\nWARNING: Purge cannot be used with redo only mode. This would purge the repository before processing redo!')
        sys.exit(1)

    if cli_args.skipRecords and cli_args.stopOnRecord and cli_args.skipRecords > cli_args.stopOnRecord:
        print('\nWARNING: The number of records to skip is greater than the record number to stop on. No work would be done!')
        sys.exit(1)

    # Check early we can read -f/-p - G2Project can handle but early out before running dbperf etc
    # Note args.projectFileSpec is a list, G2Project accepts file globbing, split to get only filename not URI
    if cli_args.projectFileSpec or cli_args.projectFileName:
        file_list = []

        # Spec such as -f /tmp/json/*.json - arg parser returns list with all json files
        #   ['/tmp/json/sample_company.json', '/tmp/json/sample_person.json']
        # Slurp up all the files that meet the wildcard
        if len(cli_args.projectFileSpec) > 1:
            file_list = cli_args.projectFileSpec

        # Spec such as -f /tmp/json/*.json/?data_source=test or -f /tmp/json/sample_person.json  - arg parser returns list with only the arg value
        #   ['/tmp/json/*.json/?data_source=test']
        # Split on /? if exists and glob the path/files
        elif len(cli_args.projectFileSpec) == 1:
            file_list = glob(cli_args.projectFileSpec[0].split('/?')[0])
        # Not a filespec it's a project file
        else:
            tokens = cli_args.projectFileName.split('/?')
            if len(tokens) > 1:
                print(f'\nERROR: Project files do not take parameters: {tokens[1]}')
                sys.exit(1)

            file_list.append(cli_args.projectFileName)

        for f in file_list:
            try:
                with open(f, 'r') as fh:
                    pass
            except IOError as ex:
                print('\nERROR: Unable to read file or project')
                print(f'       {ex}')
                sys.exit(1)

    # Check early if shuffFileRedirect is accessible and is a path
    if cli_args.shuffFileRedirect:
        shuf_path_redirect = pathlib.Path(cli_args.shuffFileRedirect[0]).resolve()
        if shuf_path_redirect.is_file() or not shuf_path_redirect.is_dir():
            print('\nERROR: The path to redirect the shuffled source file to does not exist or is a file.')
            sys.exit(1)

        # Writeable?
        try:
            test_touch = shuf_path_redirect.joinpath('senzTestTouch')
            test_touch.touch()
            test_touch.unlink()
        except IOError as ex:
            print('\nERROR: Unable to write to the path for the shuffled source file redirection.')
            print(f'       {ex}')
            sys.exit(1)

    # Test early if can create an errors file, as long as not disabled
    if not cli_args.errorsFileDisable:
        try:
            errors_file = open(cli_args.errorsFile, 'w')
            errors_file.write(str(datetime.now()) + '\n')
            errors_file.write(f'Arguments: {" ".join(sys.argv[1:])}\n')
            errors_file.flush()
        except IOError as ex:
            print('\nERROR: Unable to write to bad records file')
            print(f'       {ex}')
            sys.exit(1)
    else:
        errors_file = ''

    #Check if INI file or env var is specified, otherwise use default INI file
    ini_file_name = None

    if cli_args.iniFile:
        ini_file_name = pathlib.Path(cli_args.iniFile[0])
    elif os.getenv("SENZING_ENGINE_CONFIGURATION_JSON"):
        g2module_params = os.getenv("SENZING_ENGINE_CONFIGURATION_JSON")
    else:
        ini_file_name = pathlib.Path(G2Paths.get_G2Module_ini_path())

    if ini_file_name:
        G2Paths.check_file_exists_and_readable(ini_file_name)
        ini_param_creator = G2IniParams()
        g2module_params = ini_param_creator.getJsonINIParams(ini_file_name)

    # Are you really sure you want to purge!
    if cli_args.purgeFirst and not cli_args.forcePurge:
        if not input(textwrap.dedent('''
            WARNING: Purging (-P / --purgeFirst) will delete all loaded data and outcomes from the Senzing repository!
                     If you are unsure please contact support@senzing.com before proceeding!

                     This confirmation can be bypassed using the --FORCEPURGE command line argument, use with caution!

            Type YESPURGE to continue and purge or enter to quit:
        ''')) == "YESPURGE":
            sys.exit(0)

    # Test mode settings
    if cli_args.testMode:
        default_thread_count = 1
        cli_args.loadOutputFrequency = 10000 if cli_args.loadOutputFrequency == 1000 else cli_args.loadOutputFrequency

    # Check resources and acquire num threads
    else:
        temp_queue = Queue()
        check_resources_process = Process(target=check_resources_and_startup,
                                          args=(temp_queue,
                                                cli_args.thread_count,
                                                (cli_args.purgeFirst or cli_args.forcePurge) and not (cli_args.testMode or cli_args.redoMode)))
        check_resources_process.start()
        check_resources_process.join()
        default_thread_count = temp_queue.get()

        # Exit if checkResourcesProcess failed to start an engine
        if default_thread_count == -1:
            sys.exit(1)

    # Setup the governor(s), governor object is used for redo processing
    record_governor, source_governor, governor = governor_setup()

    # Set DSRC mode, can be overridden by dsrc_action on a record, see G2Thread()
    dsrcAction = 'A'
    if cli_args.deleteMode:
        dsrcAction = 'D'
    if cli_args.reprocessMode:
        dsrcAction = 'X'

    # Load truthset data if neither -p and -f and not in redo mode but purge was requested
    if not cli_args.projectFileName and not cli_args.projectFileSpec and not cli_args.redoMode and (cli_args.purgeFirst or cli_args.forcePurge):
        print('\nINFO: No source file or project file was specified, loading the sample truth set data...')
        # Convert the path to a string, G2Project needs updating to accommodate pathlib objects
        cli_args.projectFileName = str(pathlib.Path(os.environ.get('SENZING_ROOT', '/opt/senzing/g2/')).joinpath('python', 'demo', 'truth', 'truthset-project3.json'))

    # Running in redo only mode? Don't purge in redo only mode, would purge the queue!
    if cli_args.redoMode:
        print('\nStarting in redo only mode, processing redo queue\n')
        exit_code = load_redo_queue_and_process()
        bad_cnt = 0
    else:
        # Didn't load truthset data and nothing to do!
        if not cli_args.projectFileName and not cli_args.projectFileSpec:
            print('\nERROR: No file or project was specified to load!')
            sys.exit(1)

        exit_code, bad_cnt = perform_load()

    with suppress(Exception):
        errors_file.close()

    if not cli_args.errorsFileDisable and bad_cnt == 0 and api_errors.value == 0:
        pathlib.Path(cli_args.errorsFile).unlink()
    else:
        if not cli_args.errorsFileDisable:
            print('\nWARNING: Errors occurred during load, please check the error log file.')
        else:
            print('\nWARNING: Errors occurred during load but error file logging disabled. Logged to terminal only.')

    sys.exit(exit_code)
