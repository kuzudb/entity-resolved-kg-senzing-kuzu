# --python imports
import os


# ======================
class G2S3:

    # ----------------------------------------
    def __init__(self, uri, tempFolderPath):
        urlSplit = uri[5:].split('/')
        self.bucketName = G2S3.getBucketNameFromUri(uri)  # urlSplit[0]
        self.fileName = urlSplit[-1]
        self.localFilePath = os.sep.join(urlSplit[1:])
        self.s3filePath = "/".join(urlSplit[1:])
        self.tempFilePath = os.path.join(tempFolderPath, self.localFilePath)
        self.uri = uri

    @staticmethod
    def isS3Uri(uri):
        return uri.upper().startswith('S3://')

    @staticmethod
    def getBucketNameFromUri(uri):
        if not G2S3.isS3Uri(uri):
            print("uri \"" + uri + "\" is not a valid s3 uri. It should be of the form \"S3://<bucketName>/<fileName>\"")
            return ''
        urlSplit = uri[5:].split('/')
        return urlSplit[0]

    @staticmethod
    def getFilePathFromUri(uri):
        if not G2S3.isS3Uri(uri):
            print("uri \"" + uri + "\" is not a valid s3 uri. It should be of the form \"S3://<bucketName>/<fileName>\"")
            return ''
        split = uri[5:].split('/')
        return "/".join(split[1:])

    @staticmethod
    def ListOfS3UrisOfFilesInBucket(uri, prefix):
        bucketName = G2S3.getBucketNameFromUri(uri)
        return ['s3://' + bucketName + '/' + s for s in G2S3.filesInBucketList(uri, prefix)]

    @staticmethod
    def filesInBucketList(uri, prefix=None):
        try:
            import boto3

            bucketName = G2S3.getBucketNameFromUri(uri)
            s3 = boto3.resource('s3')
            bucket = s3.Bucket(bucketName)
            if prefix is None:
                objectList = bucket.objects.all()
            else:
                objectList = bucket.objects.filter(Prefix=prefix)

            fileList = []
            for object in objectList:
                # -- this filters out folders
                if object.key[-1] == "/":
                    continue
                fileList.append(object.key)
            return fileList
        except ImportError:
            print ('Amazon S3 package (boto3) is not installed. Please install it and try again.')
            raise
        except Exception as e:
            print('Could not list objects in bucket ' + bucketName + ' in S3')
            print(e)
            raise

    def downloadFile(self):
        try:
            import boto3
            import botocore

            s3 = boto3.resource('s3')
            bucket = s3.Bucket(self.bucketName)
            # -- ensure path exits, and that the file does not already exist
            if not os.path.exists(os.path.dirname(self.tempFilePath)):
                os.makedirs(os.path.dirname(self.tempFilePath))
            if os.path.exists(self.tempFilePath):
                os.remove(self.tempFilePath)

            # -- download file
            print('Downloading ' + os.path.basename(self.s3filePath) + ' from Amazon S3. This may take a while for large files...')
            bucket.download_file(self.s3filePath, self.tempFilePath)
            print('done.')
        except ImportError:
            print ('Amazon S3 package (boto3) is not installed. Please install it and try again.')
            raise
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                if not os.listdir(os.path.dirname(self.tempFilePath)):
                    os.rmdir(os.path.dirname(self.tempFilePath))
                print(self.fileName + ' does not exist at the URI specified: ' + self.uri)
        except OSError as e:
            if e.errno in [os.errno.EPERM, os.errno.EACCES]:
                print("Could not write to temporary file location of " + self.tempFilePath)
            raise
        except Exception as e:
            print('Could not download ' + self.s3filePath + ' from S3')
            print(e)
            raise
