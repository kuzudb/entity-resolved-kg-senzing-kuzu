#! /usr/bin/env python3

import fnmatch
import glob
import io
import json
import os
import textwrap
from contextlib import redirect_stdout
from operator import itemgetter

from CompressedFile import (fileRowParser, isCompressedFile,
                            openPossiblyCompressedFile)
from G2S3 import G2S3


# ======================
class G2Project:

    # ----------------------------------------
    def __init__(self, g2ConfigTables, dsrcAction, projectFileName=None, projectFileUri=None, tempFolderPath=None):
        """ open and validate a g2 generic configuration and project file """

        self.projectSourceList = []
        self.mappingFiles = {}

        self.dataSourceDict = g2ConfigTables.loadConfig('CFG_DSRC')
        self.featureDict = g2ConfigTables.loadConfig('CFG_FTYPE')
        self.attributeDict = g2ConfigTables.loadConfig('CFG_ATTR')

        self.f1Features = []
        for feature in self.featureDict:
            if self.featureDict[feature]['FTYPE_FREQ'] == 'F1':
                self.f1Features.append(feature)

        self.success = True
        self.mappingCache = {}
        self.tempFolderPath = tempFolderPath
        self.dsrcAction = dsrcAction

        self.clearStatPack()

        if self.success and projectFileName:
            self.loadProjectFile(projectFileName)
        elif self.success and projectFileUri:
            self.loadProjectUri(projectFileUri)
        return

    # -----------------------------
    # --mapping functions
    # -----------------------------

    # ----------------------------------------
    def lookupAttribute(self, attrName):
        ''' determine if a valid config attribute '''
        attrName = attrName.upper()
        if attrName in self.mappingCache:
            attrMapping = dict(self.mappingCache[attrName])  # dict() to create a new instance!
        else:
            usageType = ''
            configMapping = None
            if attrName in self.attributeDict:
                configMapping = self.attributeDict[attrName]
            elif '_' in attrName:
                usageType = attrName[0:attrName.find('_')]
                tryColumn = attrName[attrName.find('_') + 1:]
                if tryColumn in self.attributeDict:
                    configMapping = self.attributeDict[tryColumn]
                else:

                    usageType = attrName[attrName.rfind('_') + 1:]
                    tryColumn = attrName[0:attrName.rfind('_')]
                    if tryColumn in self.attributeDict:
                        configMapping = self.attributeDict[tryColumn]

            attrMapping = {}
            if configMapping:
                attrMapping['ATTR_CLASS'] = configMapping['ATTR_CLASS']
                attrMapping['ATTR_CODE'] = configMapping['ATTR_CODE']
                attrMapping['ATTR_ID'] = configMapping['ATTR_ID']
                attrMapping['FTYPE_CODE'] = configMapping['FTYPE_CODE']
                attrMapping['UTYPE_CODE'] = usageType
                attrMapping['FELEM_CODE'] = configMapping['FELEM_CODE']
                attrMapping['FELEM_REQ'] = configMapping['FELEM_REQ']
            else:
                attrMapping['ATTR_CLASS'] = 'OTHER'
                attrMapping['ATTR_CODE'] = None
                attrMapping['ATTR_ID'] = 0
                attrMapping['FTYPE_CODE'] = None
                attrMapping['UTYPE_CODE'] = None
                attrMapping['FELEM_CODE'] = None
                attrMapping['FELEM_REQ'] = None

            self.mappingCache[attrName] = attrMapping

        return attrMapping

    # ---------------------------------------
    def mapAttribute(self, attrName, attrValue):
        ''' places mapped column values into a feature structure '''

        # --strip spaces and ensure a string
        if not str(attrValue).strip():
            return None

        attrMapping = self.lookupAttribute(attrName)
        attrMapping['ATTR_NAME'] = attrName
        attrMapping['ATTR_VALUE'] = attrValue

        return attrMapping

    # ----------------------------------------
    def testJsonRecord(self, jsonDict, rowNum, sourceDict):

        mappingErrors = []
        mappedAttributeList = []
        mappedFeatures = {}
        entityName = None
        self.recordCount += 1

        # --parse the json
        for columnName in jsonDict:
            if type(jsonDict[columnName]) == list:
                childRowNum = -1
                for childRow in jsonDict[columnName]:
                    childRowNum += 1
                    if type(childRow) != dict:
                        mappingErrors.append('expected records in list under %s' % columnName)
                        break
                    else:
                        for childColumn in childRow:
                            if type(jsonDict[columnName][childRowNum][childColumn]) not in (dict, list):  # safeguard:
                                mappedAttribute = self.mapAttribute(childColumn, jsonDict[columnName][childRowNum][childColumn])
                                if mappedAttribute:
                                    mappedAttribute['ATTR_LEVEL'] = columnName + '#' + str(childRowNum)
                                    mappedAttributeList.append(mappedAttribute)
                            else:
                                mappingErrors.append('unexpected records under %s of %s' % (childColumn, columnName))
                                break

            elif type(jsonDict[columnName]) != dict:  # safeguard
                mappedAttribute = self.mapAttribute(columnName, jsonDict[columnName])
                if mappedAttribute:
                    mappedAttribute['ATTR_LEVEL'] = 'ROOT'
                    mappedAttributeList.append(mappedAttribute)
            else:
                mappingErrors.append('unexpected records under %s' % columnName)

        if mappingErrors:
            self.updateStatPack('ERROR', 'Invalid JSON structure', 'row: ' + str(rowNum))
        else:

            # --create a feature key to group elements that go together
            elementKeyVersions = {}
            for i in range(len(mappedAttributeList)):
                if mappedAttributeList[i]['FTYPE_CODE']:
                    if mappedAttributeList[i]['UTYPE_CODE']:
                        featureKey = mappedAttributeList[i]['ATTR_LEVEL'] + '-' + mappedAttributeList[i]['FTYPE_CODE'] + '-' + mappedAttributeList[i]['UTYPE_CODE']
                        elementKey = mappedAttributeList[i]['ATTR_LEVEL'] + '-' + mappedAttributeList[i]['FTYPE_CODE'] + '-' + mappedAttributeList[i]['UTYPE_CODE'] + '-' + mappedAttributeList[i]['FELEM_CODE']
                    else:
                        featureKey = mappedAttributeList[i]['ATTR_LEVEL'] + '-' + mappedAttributeList[i]['FTYPE_CODE']
                        elementKey = mappedAttributeList[i]['ATTR_LEVEL'] + '-' + mappedAttributeList[i]['FTYPE_CODE'] + '-' + mappedAttributeList[i]['FELEM_CODE']

                    if elementKey in elementKeyVersions:
                        elementKeyVersions[elementKey] += 1
                    else:
                        elementKeyVersions[elementKey] = 0
                    mappedAttributeList[i]['FEATURE_KEY'] = featureKey + '-' + str(elementKeyVersions[elementKey])
                else:
                    mappedAttributeList[i]['FEATURE_KEY'] = ""

            # --validate and count the features
            featureCount = 0
            mappedAttributeList = sorted(mappedAttributeList, key=itemgetter('FEATURE_KEY', 'ATTR_ID'))
            mappedAttributeListLength = len(mappedAttributeList)
            i = 0
            while i < mappedAttributeListLength:
                if mappedAttributeList[i]['FEATURE_KEY']:

                    featureKey = mappedAttributeList[i]['FEATURE_KEY']
                    ftypeClass = mappedAttributeList[i]['ATTR_CLASS']
                    ftypeCode = mappedAttributeList[i]['FTYPE_CODE']
                    usageType = mappedAttributeList[i]['UTYPE_CODE']
                    featureDesc = ''
                    attrList = []
                    completeFeature = False
                    while i < mappedAttributeListLength and mappedAttributeList[i]['FEATURE_KEY'] == featureKey:
                        attrCode = mappedAttributeList[i]['ATTR_CODE']
                        attrValue = mappedAttributeList[i]['ATTR_VALUE']
                        if attrCode != ftypeCode:
                            self.updateStatPack('MAPPED', f'{ftypeCode}|{usageType}|{attrCode}', attrValue)
                        if mappedAttributeList[i]['FELEM_CODE'] == 'USAGE_TYPE':
                            usageType = mappedAttributeList[i]['ATTR_VALUE']
                        elif mappedAttributeList[i]['FELEM_CODE'].upper() not in ('USED_FROM_DT', 'USED_THRU_DT'):
                            if len(str(mappedAttributeList[i]['ATTR_VALUE'])) if mappedAttributeList[i]['ATTR_VALUE'] is not None else 0:  # can't count null values
                                attrList.append(attrCode)
                                featureDesc += ' ' + str(mappedAttributeList[i]['ATTR_VALUE'])
                                if mappedAttributeList[i]['FELEM_REQ'].upper() in ('YES', 'ANY'):
                                    completeFeature = True
                        i += 1

                    if not completeFeature:
                        self.updateStatPack('INFO', f'Incomplete {ftypeCode}', f'row {self.recordCount}')
                    else:
                        self.updateStatPack('MAPPED', f'{ftypeCode}|{usageType}|n/a', featureDesc.strip())
                        featureCount += 1

                        # --update mapping stats
                        statCode = ftypeCode + ('-' + usageType if usageType else '')
                        if statCode in self.featureStats:
                            self.featureStats[statCode] += 1
                        else:
                            self.featureStats[statCode] = 1

                        # --use first name encountered as the entity description
                        if ftypeCode == 'NAME' and not entityName:
                            entityName = featureDesc

                        # --capture feature stats for validation
                        validationData = {'USAGE_TYPE': usageType, 'ATTR_LIST': attrList}
                        if ftypeCode not in mappedFeatures:
                            mappedFeatures[ftypeCode] = [validationData]
                        else:
                            mappedFeatures[ftypeCode].append(validationData)

                else:
                    # --this is an unmapped attribute
                    if mappedAttributeList[i]['ATTR_CLASS'] == 'OTHER':

                        # --update mapping stats
                        statCode = mappedAttributeList[i]['ATTR_NAME']
                        if statCode in self.unmappedStats:
                            self.unmappedStats[statCode] += 1
                        else:
                            self.unmappedStats[statCode] = 1

                        attrCode = mappedAttributeList[i]['ATTR_NAME']
                        attrValue = mappedAttributeList[i]['ATTR_VALUE']
                        self.updateStatPack('UNMAPPED', attrCode, attrValue)

                    elif mappedAttributeList[i]['ATTR_CLASS'] == 'OBSERVATION':
                        attrCode = mappedAttributeList[i]['ATTR_NAME']
                        attrValue = mappedAttributeList[i]['ATTR_VALUE']
                        self.updateStatPack('MAPPED', 'n/a||' + attrCode, attrValue)  # "n/a||"" to give same structure as an actual feature

                    i += 1

            # --errors and warnings
            messageList = []
            if self.dsrcAction == 'A' and featureCount == 0:
                messageList.append(['ERROR', 'No features mapped'])

            # --required missing values
            if 'DATA_SOURCE' not in jsonDict and 'DATA_SOURCE' not in sourceDict:
                messageList.append(['ERROR', 'Data source missing'])
            # Which one should be used? Easy to assume wrong one, error and allow user to correct
            if 'DATA_SOURCE' in jsonDict and 'DATA_SOURCE' in sourceDict and jsonDict['DATA_SOURCE'] != sourceDict['DATA_SOURCE']:
                messageList.append(['ERROR', f'Data source specified in record {jsonDict["DATA_SOURCE"]} and command line {sourceDict["DATA_SOURCE"]}'])
            # --this next condition is confusing because if they specified data source for the file (sourcedict) it will be added automatically
            # --so if the data source was not specified for the file its in the json record and needs to be validated
            elif 'DATA_SOURCE' not in sourceDict and jsonDict['DATA_SOURCE'].upper() not in self.dataSourceDict:
                messageList.append(['ERROR', 'Invalid data source: ' + jsonDict['DATA_SOURCE'].upper()])
            # If the data source is specified on the command line, warn it will be added. This doesn't apply to data sources in records
            elif 'DATA_SOURCE' in sourceDict and sourceDict['DATA_SOURCE'] and sourceDict['DATA_SOURCE'] not in self.dataSourceDict:
                messageList.append(['INFO', 'Data source doesn\'t exist, will be added: ' + sourceDict['DATA_SOURCE']])

            # --record_id
            if 'RECORD_ID' not in jsonDict:
                messageList.append(['INFO', 'Record ID is missing'])
                record_id = ''
            else:
                record_id = jsonDict['RECORD_ID']

            # --name warnings
            if 'NAME' not in mappedFeatures:
                messageList.append(['INFO', 'Missing Name'])
            else:
                crossAttrList = []
                for validationData in mappedFeatures['NAME']:
                    crossAttrList += validationData['ATTR_LIST']
                    if 'NAME_FULL' in validationData['ATTR_LIST'] and any(item in validationData['ATTR_LIST'] for item in ['NAME_FIRST', 'NAME_LAST', 'NAME_ORG']):
                        messageList.append(['INFO', 'Full name should be mapped alone'])
                    elif 'NAME_LAST' in validationData['ATTR_LIST'] and 'NAME_FIRST' not in validationData['ATTR_LIST']:
                        messageList.append(['INFO', 'Last name without first name'])
                    elif 'NAME_FIRST' in validationData['ATTR_LIST'] and 'NAME_LAST' not in validationData['ATTR_LIST']:
                        messageList.append(['INFO', 'First name without last name'])
                if 'NAME_ORG' in crossAttrList and any(item in crossAttrList for item in ['NAME_FIRST', 'NAME_LAST']):
                    messageList.append(['WARNING', 'Organization and person names on same record'])

            # --address warnings
            if 'ADDRESS' in mappedFeatures:
                for validationData in mappedFeatures['ADDRESS']:
                    if 'ADDR_FULL' in validationData['ATTR_LIST']:
                        if any(item in validationData['ATTR_LIST'] for item in ['ADDR_LINE1', 'ADDR_CITY', 'ADDR_STATE', 'ADDR_POSTAL_CODE', 'ADDR_COUNTRY']):
                            messageList.append(['INFO', 'Full address should be mapped alone'])
                    else:
                        if 'ADDR_LINE1' not in validationData['ATTR_LIST']:
                            messageList.append(['INFO', 'Address line1 is missing'])
                        if 'ADDR_CITY' not in validationData['ATTR_LIST']:
                            messageList.append(['INFO', 'Address city is missing'])
                        if 'ADDR_POSTAL_CODE' not in validationData['ATTR_LIST']:
                            messageList.append(['INFO', 'Address postal code is missing'])

            # --other warnings
            if 'OTHER_ID' in mappedFeatures:
                if len(mappedFeatures['OTHER_ID']) > 1:
                    messageList.append(['INFO', 'Multiple other_ids mapped'])
                else:
                    messageList.append(['INFO', 'Use of other_id feature'])

            for message in messageList:
                self.updateStatPack(message[0], message[1], 'row: ' + str(rowNum) + (', record_id: ' + str(record_id) if record_id else ''))
                mappingErrors.append(message)

        return [mappingErrors, mappedAttributeList, entityName]

    # ---------------------------------------
    def clearStatPack(self):
        ''' clear the statistics on demand '''
        self.recordCount = 0
        self.statPack = {}

        self.featureStats = {}
        self.unmappedStats = {}
        return

    # ----------------------------------------
    def updateStatPack(self, cat1, cat2, value=None):

        if cat1 not in self.statPack:
            self.statPack[cat1] = {}
        if cat2 not in self.statPack[cat1]:
            self.statPack[cat1][cat2] = {'COUNT': 1, 'VALUES': {}}
        else:
            self.statPack[cat1][cat2]['COUNT'] += 1

        if value:
            if value not in self.statPack[cat1][cat2]['VALUES']:
                self.statPack[cat1][cat2]['VALUES'][value] = 1
            else:
                self.statPack[cat1][cat2]['VALUES'][value] += 1

        return

    # ---------------------------------------
    def getStatPack(self):
        statPack = {}
        fileWarnings = []
        for cat1 in self.statPack:
            itemList = []
            for cat2 in self.statPack[cat1]:
                reclass_warning = False
                itemDict = {}
                if cat1 == 'MAPPED':
                    cat2parts = cat2.split('|')
                    itemDict['feature'] = cat2parts[0]
                    itemDict['label'] = cat2parts[1]
                    itemDict['attribute'] = cat2parts[2]
                    itemDict['featId'] = self.featureDict[cat2parts[0]]['ID'] if cat2parts[0] != 'n/a' else 0
                    itemDict['attrId'] = self.attributeDict[cat2parts[2]]['ATTR_ID'] if cat2parts[2] != 'n/a' else 0
                    if not itemDict['attrId']:
                        itemDict['description'] = itemDict['feature'] + (' - ' + itemDict['label'] if itemDict['label'] else '')
                    elif not itemDict['featId']:
                        itemDict['description'] = itemDict['attribute']
                    else:
                        itemDict['description'] = '  ' + itemDict['attribute'].lower()

                elif cat1 == 'UNMAPPED':
                    itemDict['attribute'] = cat2
                else:
                    itemDict['type'] = cat1
                    itemDict['message'] = cat2

                itemDict['recordCount'] = self.statPack[cat1][cat2]['COUNT']
                itemDict['recordPercent'] = self.statPack[cat1][cat2]['COUNT'] / self.recordCount if self.recordCount else 0
                if cat1 in ('MAPPED', 'UNMAPPED'):
                    itemDict['uniqueCount'] = len(self.statPack[cat1][cat2]['VALUES'])
                    itemDict['uniquePercent'] = itemDict['uniqueCount'] / itemDict['recordCount'] if itemDict['recordCount'] else 0

                # --feature warnings (not statistically relevant on small amounts of data)
                if cat1 == 'MAPPED' and itemDict['attrId'] == 0 and itemDict['recordCount'] >= 1000:
                    itemDict['frequency'] = self.featureDict[cat2parts[0]]['FTYPE_FREQ']
                    if itemDict['frequency'] == 'F1' and itemDict['uniquePercent'] < .8:
                        itemDict['warning'] = True
                        msg = itemDict['feature'] + ' is only ' + str(round(itemDict['uniquePercent'] * 100, 0)) + '% unique'
                        fileWarnings.append({'type': 'WARNING', 'message': msg, 'recordCount': itemDict['uniqueCount'], 'recordPercent': itemDict['uniquePercent']})
                    if itemDict['frequency'] == 'NAME' and itemDict['uniquePercent'] < .7:
                        itemDict['warning'] = True
                        msg = itemDict['feature'] + ' is only ' + str(round(itemDict['uniquePercent'] * 100, 0)) + '% unique'
                        fileWarnings.append({'type': 'WARNING', 'message': msg, 'recordCount': itemDict['uniqueCount'], 'recordPercent': itemDict['uniquePercent']})
                    if itemDict['frequency'] == 'FF' and itemDict['uniquePercent'] < .7:
                        itemDict['warning'] = True
                        msg = itemDict['feature'] + ' is only ' + str(round(itemDict['uniquePercent'] * 100, 0)) + '% unique'
                        fileWarnings.append({'type': 'WARNING', 'message': msg, 'recordCount': itemDict['uniqueCount'], 'recordPercent': itemDict['uniquePercent']})

                # --reclass prevalent informational messages to warnings
                elif cat1 == 'INFO' and itemDict['recordPercent'] >= .5:
                    reclass_warning = True

                itemDict['topValues'] = []
                for value in sorted(self.statPack[cat1][cat2]['VALUES'].items(), key=lambda x: x[1], reverse=True):
                    itemDict['topValues'].append('%s (%s)' % value)
                    if len(itemDict['topValues']) == 10:
                        break

                if reclass_warning:
                    fileWarnings.append(itemDict)
                else:
                    itemList.append(itemDict)

            if cat1 == 'MAPPED':
                statPack[cat1] = sorted(itemList, key=lambda x: (x['featId'], x['label'], x['attrId']))
            elif cat1 == 'UNMAPPED':
                statPack[cat1] = sorted(itemList, key=lambda x: x['attribute'])
            else:
                statPack[cat1] = sorted(itemList, key=lambda x: x['recordCount'], reverse=True)

        if fileWarnings and 'WARNING' not in statPack:
            statPack['WARNING'] = []
        for itemDict in fileWarnings:
            itemDict['type'] = 'WARNING'
            statPack['WARNING'].insert(0, itemDict)

        return statPack

    # -----------------------------
    # --project functions
    # -----------------------------

    def loadProjectUri(self, fileSpec):
        ''' creates a project dictionary from a file spec '''

        for file in fileSpec:

            parmDict = {}
            parmString = ''
            parmList = []
            # Have additional parameters been specified?
            if '/?' in file:
                # Split what we are expecting and anything else discard
                fileSpec, parmString, *_ = file.split('/?')
                parmList = parmString.split(',')

                for parm in parmList:
                    if '=' in parm:
                        parmType = parm.split('=')[0].strip().upper()
                        parmValue = parm.split('=')[1].strip().replace('"', '').replace("'", '').upper()
                        parmDict[parmType] = parmValue
            # If not additional parameters use file to enable easy file globbing where fileSpec would otherwise be a list and file isn't
            # fileSpec is a str when /? is present but a list when it isn't present this addresses that
            else:
                fileSpec = file

            # --try to determine file_format
            if 'FILE_FORMAT' not in parmDict:
                if 'FILE_TYPE' in parmDict:
                    parmDict['FILE_FORMAT'] = parmDict['FILE_TYPE']
                else:
                    _, fileExtension = os.path.splitext(fileSpec)

                    # G2Loader appends _-_SzShuf*_-_ to shuf files and _-_SzShufNoDel_-_<timestamp> to non-delete shuf files
                    # Strip these off to locate file extension to allow for loading of shuf files
                    if '_-_SzShuf' in fileSpec:
                        try:
                            fileExtension = fileExtension[:fileExtension.index('_-_SzShuf')]
                        except ValueError:
                            pass

                    # If looks like a compressed file, strip off the first extension (.gz, .gzip, zip) to locate the real extension (.json, .csv)
                    if isCompressedFile(fileSpec):
                        remain_fileSpec, _ = os.path.splitext(fileSpec)
                        _, fileExtension = os.path.splitext(remain_fileSpec)

                    parmDict['FILE_FORMAT'] = fileExtension.replace('.', '').upper()

            if parmDict['FILE_FORMAT'] not in ('JSON', 'JSONL', 'CSV', 'UMF', 'TAB', 'TSV', 'PIPE', 'GZ', 'GZIP'):
                print(textwrap.dedent(f'''\n
                    ERROR: File format must be one of JSON, JSONL, CSV, UMF, TAB, TSV, PIPE or specify file_format with the -f argument.

                               - ./G2Loader.py -f my_file.csv/?data_source=EXAMPLE
                               - ./G2Loader.py -f my_file.txt/?data_source=EXAMPLE,file_format=CSV

                           - If using a wildcard such as -f files_to_load* all files must have the same extension or use file_format=<format>

                               - ./G2Loader.py -f my_file*.csv/?data_source=EXAMPLE
                               - ./G2Loader.py -f my_file*/?data_source=EXAMPLE,file_format=CSV

                           - File format detected: {parmDict['FILE_FORMAT'] if parmDict['FILE_FORMAT'] else 'None'}
                '''))
                self.success = False
            else:
                if G2S3.isS3Uri(fileSpec):
                    s3list = G2S3.ListOfS3UrisOfFilesInBucket(fileSpec, os.path.dirname(G2S3.getFilePathFromUri(fileSpec)))
                    fileList = fnmatch.filter(s3list, fileSpec)
                else:
                    if fileSpec.upper().startswith('FILE://'):
                        fileSpec = fileSpec[7:]
                    try:
                        fileList = glob.glob(fileSpec)
                    except:
                        fileList = []

                if not fileList:
                    print('\nERROR: File specification did not return any files!')
                    self.success = False
                else:
                    self.projectFileName = 'n/a'
                    self.projectFilePath = os.path.dirname(os.path.abspath(fileList[0]))
                    for fileName in fileList:
                        sourceDict = {}
                        sourceDict['FILE_NAME'] = fileName
                        sourceDict['FILE_FORMAT'] = parmDict['FILE_FORMAT']
                        if 'DATA_SOURCE' in parmDict:
                            sourceDict['DATA_SOURCE'] = parmDict['DATA_SOURCE']
                        self.projectSourceList.append(sourceDict)

        if self.success:
            self.prepareSourceFiles()

        return

    # ----------------------------------------
    def loadProjectFile(self, projectFileName):
        ''' ensures the project file exists, is valid and kicks off correct processor - csv or json '''
        # --hopefully its a valid project file
        if os.path.exists(projectFileName):

            self.projectFileName = projectFileName
            self.projectFilePath = os.path.dirname(os.path.abspath(projectFileName))
            fileName, fileExtension = os.path.splitext(projectFileName)

            if fileExtension.upper() == '.JSON':
                self.projectFileFormat = 'JSON'
            elif fileExtension.upper() in ('.CSV', '.TSV', '.TAB', '.PIPE'):
                self.projectFileFormat = fileExtension[1:].upper()
            else:
                print('ERROR: Invalid project file extension [%s]' % fileExtension)
                print(' Supported project file extensions include: .json, .csv, .tsv, .tab, and .pipe')
                self.success = False
                return

            # --load a json project file
            if self.projectFileFormat == 'JSON':
                self.loadJsonProject()

            # --its gotta be a csv dialect
            else:
                self.loadCsvProject()

            if self.success:
                self.prepareSourceFiles()
        else:
            print('ERROR: project file ' + projectFileName + ' not found!')
            self.success = False

        return

    # ----------------------------------------
    def loadJsonProject(self):
        ''' validates and loads a json project file into memory '''
        try:
            projectData = json.load(open(self.projectFileName, encoding="utf-8"))
        except Exception as err:
            print('ERROR: project file ' + repr(err))
            self.success = False
        else:
            projectData = self.dictKeysUpper(projectData)
            if type(projectData) == list:
                projectData = {'DATA_SOURCES': projectData}

            if 'DATA_SOURCES' in projectData:
                sourceRow = 0
                for sourceDict in projectData['DATA_SOURCES']:
                    sourceRow += 1
                    if 'FILE_NAME' not in sourceDict:
                        print('ERROR: project file entry ' + str(sourceRow) + ' does not contain an entry for FILE_NAME!')
                        self.success = False
                        break
                    self.projectSourceList.append(sourceDict)

        if len(self.projectSourceList) == 0:
            print('ERROR: project file does not contain any data sources!')

        return

    # ----------------------------------------
    def loadCsvProject(self):

        fileData = {
            'FILE_NAME': self.projectFileName,
            'FILE_FORMAT': self.projectFileFormat
        }

        if self.projectFileFormat == 'CSV':
            fileData['DELIMITER'] = ','
        elif self.projectFileFormat in ('TSV', 'TAB'):
            fileData['DELIMITER'] = '\t'
        elif self.projectFileFormat == 'PIPE':
            fileData['DELIMITER'] = '|'

        fileData['MULTICHAR_DELIMITER'] = False

        csvFile = openPossiblyCompressedFile(self.projectFileName, 'r')
        fileData['HEADER_ROW'] = [x.strip().upper() for x in fileRowParser(next(csvFile), fileData)]

        if not(fileData['HEADER_ROW']):
            print('ERROR: project file does not contain a header row!')
            self.success = False
        elif 'FILE_NAME' not in fileData['HEADER_ROW']:
            print('ERROR: project file does not contain a column for FILE_NAME!')
            self.success = False
        else:
            for line in csvFile:
                rowData = fileRowParser(line, fileData)
                if rowData:  # --skip blank lines
                    self.projectSourceList.append(rowData)

        csvFile.close()

        return

    # ----------------------------------------
    def prepareSourceFiles(self):
        ''' ensure project files referenced exist and are valid '''

        print()
        self.sourceList = []
        sourceRow = 0

        for sourceDict in self.projectSourceList:
            sourceRow += 1

            # --bypass if disabled
            if 'ENABLED' in sourceDict and str(sourceDict['ENABLED']).upper() in ('0', 'N', 'NO'):
                continue

            # --validate source file
            sourceDict['FILE_NAME'] = sourceDict['FILE_NAME'].strip()
            if len(sourceDict['FILE_NAME']) == 0:
                print('ERROR: project file entry ' + str(sourceRow) + ' does not contain a FILE_NAME!')
                self.success = False

            if 'DATA_SOURCE' in sourceDict:
                sourceDict['DATA_SOURCE'] = sourceDict['DATA_SOURCE'].strip().upper()

            if 'FILE_FORMAT' not in sourceDict:
                fileName, fileExtension = os.path.splitext(sourceDict['FILE_NAME'])
                sourceDict['FILE_FORMAT'] = fileExtension[1:].upper()
            else:
                sourceDict['FILE_FORMAT'] = sourceDict['FILE_FORMAT'].upper()

            if sourceDict['FILE_FORMAT'] not in ('JSON', 'JSONL', 'CSV', 'TSV', 'TAB', 'PIPE', 'UMF'):
                print('ERROR: project file entry ' + str(sourceRow) + ' does not contain a valid file format!')
                self.success = False

            # --csv stuff
            sourceDict['ENCODING'] = sourceDict['ENCODING'] if 'ENCODING' in sourceDict else 'utf-8-sig'
            sourceDict['DELIMITER'] = sourceDict['DELIMITER'] if 'DELIMITER' in sourceDict else None

            if not sourceDict['DELIMITER']:
                if sourceDict['FILE_FORMAT'] == 'CSV':
                    sourceDict['DELIMITER'] = ','
                elif sourceDict['FILE_FORMAT'] in ('TSV', 'TAB'):
                    sourceDict['DELIMITER'] = '\t'
                elif sourceDict['FILE_FORMAT'] == 'PIPE':
                    sourceDict['DELIMITER'] = '|'
                else:
                    sourceDict['DELIMITER'] = ''
            else:
                sourceDict['DELIMITER'] = str(sourceDict['DELIMITER'])
            sourceDict['MULTICHAR_DELIMITER'] = len(sourceDict['DELIMITER']) > 1
            sourceDict['QUOTECHAR'] = sourceDict['QUOTECHAR'] if 'QUOTECHAR' in sourceDict else None

            # --csv mapping stuff
            if 'MAPPING_FILE' in sourceDict:
                if not os.path.exists(sourceDict['MAPPING_FILE']):
                    sourceDict['MAPPING_FILE'] = self.projectFilePath + os.path.sep + sourceDict['MAPPING_FILE']
                if sourceDict['MAPPING_FILE'] not in self.mappingFiles:
                    if not os.path.exists(sourceDict['MAPPING_FILE']):
                        print('ERROR: Mapping file %s does not exist for project file entry %s' % (sourceDict['MAPPING_FILE'], str(sourceRow)))
                        self.success = False
                    else:
                        try:
                            mappingFileDict = json.load(open(sourceDict['MAPPING_FILE']))
                        except ValueError as err:
                            print('ERROR: Invalid json in mapping file  %s' % (sourceDict['MAPPING_FILE']))
                            print(err)
                            self.success = False
                        else:
                            self.mappingFiles[sourceDict['MAPPING_FILE']] = self.dictKeysUpper(mappingFileDict)
            else:
                sourceDict['MAPPING_FILE'] = None

            # --validate and map the files for this source
            if self.success:
                if G2S3.isS3Uri(sourceDict['FILE_NAME']):
                    # --an S3 path so download the file to the temp location
                    downloader = G2S3(sourceDict['FILE_NAME'], self.tempFolderPath)
                    downloader.downloadFile()
                    sourceDict['FILE_PATH'] = downloader.tempFilePath
                    sourceDict['FILE_NAME'] = downloader.fileName
                    sourceDict['FILE_SOURCE'] = "S3"
                elif os.path.exists(sourceDict['FILE_NAME']):
                    # --adjustment if they gave us full path as file name
                    sourceDict['FILE_PATH'] = sourceDict['FILE_NAME']
                    sourceDict['FILE_NAME'] = os.path.basename(sourceDict['FILE_PATH'])
                    sourceDict['FILE_SOURCE'] = 'local'
                else:  # append the project file path
                    sourceDict['FILE_PATH'] = self.projectFilePath + os.path.sep + sourceDict['FILE_NAME']
                    sourceDict['FILE_SOURCE'] = 'local'

                print(f'\nValidating {sourceDict["FILE_PATH"]}...')

                if not os.path.exists(sourceDict['FILE_PATH']):
                    print(' ERROR: File does not exist!')
                    self.success = False
                else:

                    # --test first 100 rows
                    rowCnt = 0
                    badCnt = 0
                    fileReader = openPossiblyCompressedFile(sourceDict['FILE_PATH'], 'r', sourceDict['ENCODING'])

                    # --get header row if csv
                    if sourceDict['FILE_FORMAT'] not in ('JSON', 'JSONL', 'UMF'):
                        sourceDict['HEADER_ROW'] = [x.strip().upper() for x in fileRowParser(next(fileReader), sourceDict)]

                    for row in fileReader:
                        rowCnt += 1
                        if rowCnt > 100:
                            rowCnt -= 1
                            break

                        rowData = fileRowParser(row, sourceDict, rowCnt)
                        if not rowData:
                            badCnt += 1
                            continue

                        if sourceDict['FILE_FORMAT'] == 'UMF':
                            if not (rowData.upper().startswith('<UMF_DOC') and rowData.upper().endswith('/UMF_DOC>')):
                                print('WARNING: invalid UMF in row %s (%s)' % (rowCnt, rowData[0:50]))
                                badCnt += 1
                        else:  # test json or csv record
                            mappingResponse = self.testJsonRecord(rowData, rowCnt, sourceDict)
                            for mappingError in mappingResponse[0]:
                                if mappingError[0] == 'ERROR':
                                    print(f'    {mappingError[0]}: Row {rowCnt} - {mappingError[1]}')
                                    badCnt += 1

                    # --fails if too many bad records (more than 10 of 100 or all bad)
                    if badCnt >= 10 or badCnt == rowCnt:
                        print(f'\nERROR: Pre-test failed {badCnt} bad records in first {rowCnt}')
                        self.success = False

                    fileReader.close()

            if self.success:
                self.sourceList.append(sourceDict)

        return

    # ----------------------------------------
    def dictKeysUpper(self, in_dict):
        if type(in_dict) is dict:
            out_dict = {}
            for key, item in in_dict.items():
                out_dict[key.upper()] = self.dictKeysUpper(item)
            return out_dict
        elif type(in_dict) is list:
            return [self.dictKeysUpper(obj) for obj in in_dict]
        else:
            return in_dict

    # -----------------------------
    # --report functions
    # -----------------------------

    def getTestResults(self, reportStyle='Full'):
        statPack = self.getStatPack()

        with io.StringIO() as buf, redirect_stdout(buf):

            print('\nTEST RESULTS')

            if 'MAPPED' in statPack:
                tableInfo = [{'header': 'MAPPED FEATURES', 'width': 40, 'just': '<'},
                             {'header': 'UniqueCount', 'width': 0, 'just': '>', 'style': ','},
                             {'header': 'UniquePercent', 'width': 0, 'just': '>', 'style': '.1%'},
                             {'header': 'RecordCount', 'width': 0, 'just': '>', 'style': ','},
                             {'header': 'RecordPercent', 'width': 0, 'just': '>', 'style': '.1%'}]
                if reportStyle == 'F':
                    for i in range(10):
                        tableInfo.append({'header': f'Top used value {i+1}', 'width': 50})
                tableData = []
                for itemDict in statPack['MAPPED']:
                    rowData = [itemDict['description'], itemDict['uniqueCount'], itemDict['uniquePercent'],
                               itemDict['recordCount'], itemDict['recordPercent']]
                    if reportStyle == 'F':
                        for i in range(10):
                            if i < len(itemDict['topValues']):
                                rowData.append(itemDict['topValues'][i])
                            else:
                                rowData.append('')
                    tableData.append(rowData)

                print()
                self.renderTable(tableInfo, tableData)

            if 'UNMAPPED' in statPack:
                tableInfo[0]['header'] = 'UNMAPPED ATTRIBUTES'
                tableData = []
                for itemDict in statPack['UNMAPPED']:
                    rowData = [itemDict['attribute'], itemDict['uniqueCount'], itemDict['uniquePercent'],
                               itemDict['recordCount'], itemDict['recordPercent']]
                    if reportStyle == 'F':
                        for i in range(10):
                            if i < len(itemDict['topValues']):
                                rowData.append(itemDict['topValues'][i])
                            else:
                                rowData.append('')
                    tableData.append(rowData)

                print()
                self.renderTable(tableInfo, tableData)

            for msgType in ['ERROR', 'WARNING', 'INFO']:
                if msgType in statPack:
                    tableInfo = [{'header': msgType, 'width': 66, 'just': '<'},
                                 {'header': 'RecordCount', 'width': 0, 'just': '>', 'style': ','},
                                 {'header': 'RecordPercent', 'width': 0, 'just': '>', 'style': '.1%'}]
                    if reportStyle == 'F':
                        for i in range(10):
                            tableInfo.append({'header': f'Example: {i+1}', 'width': 50})
                    tableData = []
                    for itemDict in statPack[msgType]:
                        rowData = [itemDict['message'], itemDict['recordCount'], itemDict['recordPercent']]
                        if reportStyle == 'F':
                            for i in range(10):
                                if 'topValues' in itemDict and i < len(itemDict['topValues']):
                                    rowData.append(itemDict['topValues'][i])
                                else:
                                    rowData.append('')
                        tableData.append(rowData)

                    print()
                    self.renderTable(tableInfo, tableData)

            if 'ERROR' in statPack or 'WARNING' in statPack:
                print('\n** PLEASE REVISIT THE MAPPINGS FOR THIS FILE BEFORE LOADING IT **')
            else:
                print('\nNO ERRORS OR WARNINGS DETECTED')

            return buf.getvalue()
        return ''

    def renderTable(self, tableInfo, tableData):
        hdrFormat = ''
        rowFormat = ''
        headerRow1 = []
        headerRow2 = []
        for columnInfo in tableInfo:
            if 'width' not in columnInfo or columnInfo['width'] == 0:
                columnInfo['width'] = len(columnInfo['header'])
            if 'just' not in columnInfo:
                columnInfo['just'] = '<'
            hdrFormat += '{:' + columnInfo['just'] + str(columnInfo['width']) + '} '
            rowFormat += '{:' + columnInfo['just'] + str(columnInfo['width']) + (columnInfo['style'] if 'style' in columnInfo else '') + '} '
            headerRow1.append(columnInfo['header'])
            headerRow2.append('-' * columnInfo['width'])

        print(hdrFormat.format(*headerRow1))
        print(hdrFormat.format(*headerRow2))
        for row in tableData:
            print(rowFormat.format(*row))
