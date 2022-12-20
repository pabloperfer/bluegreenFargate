import boto3
import os
from botocore.client import Config
import zipfile
import json

elb_name = os.environ.get('ELB_NAME')
describe_alb = None

def handler():

    # we get the build id and the environment variables
    build_id = get_build_artifact_id(get_build_execution_id())
    
    access=os.environ.get('AWS_ACCESS_KEY_ID_Target')
    secret=os.environ.get('AWS_SECRET_ACCESS_KEY_Target')
    session=os.environ.get('AWS_SESSION_TOKEN_Target')
    elb_client = boto3.client(
    'elbv2',
    aws_access_key_id=access,
    aws_secret_access_key=secret,
    aws_session_token=session,)

    # If load balancer exists we set the tags for the target group in the output file corresponding to the service
    # that is in production and set the tag with the resulting from the previous build stage where we built the image
    # for the service that is not in production.
    # We invoke the find_b_targetgroup function which will return the tag key and the sha of the image for the ports 443 and 8443
    if check_alb_exists():
        b_id, b_sha, l_id, l_sha = find_b_targetgroup()
        cf_inputs = { b_id:str(build_id),l_id:l_sha }
    else:
        cf_inputs = {"Code1": str(build_id), "Code2": str(build_id)}
    with open('cf_inputs.json', 'w+') as outfile:
        json.dump(cf_inputs, outfile)

def check_alb_exists():

    global describe_alb
    try:
        access=os.environ.get('AWS_ACCESS_KEY_ID_Target')
        secret=os.environ.get('AWS_SECRET_ACCESS_KEY_Target')
        session=os.environ.get('AWS_SESSION_TOKEN_Target')
        elb_client = boto3.client(
            'elbv2',
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            aws_session_token=session,)

        describe_alb = elb_client.describe_load_balancers(Names=[elb_name])

        return True
    except Exception as e: 
        print(e)
        return False


def find_b_targetgroup():
    # returns the tag value of target groups running on 8443 and 443 and the sha of each image for the production and non production port

    access=os.environ.get('AWS_ACCESS_KEY_ID_Target')
    secret=os.environ.get('AWS_SECRET_ACCESS_KEY_Target')
    session=os.environ.get('AWS_SESSION_TOKEN_Target')
    elb_client = boto3.client(
    'elbv2',
    aws_access_key_id=access,
    aws_secret_access_key=secret,
    aws_session_token=session,)
    listners = elb_client.describe_listeners(LoadBalancerArn=describe_alb['LoadBalancers'][0]['LoadBalancerArn'])
    for x in listners['Listeners']:
        if (x['Port'] == 443):
            livelistenerarn = x['ListenerArn']
        if (x['Port'] == 8443):
            betalistenerarn = x['ListenerArn']

    b_tgp_response = elb_client.describe_rules(ListenerArn=betalistenerarn)
    l_tgp_response = elb_client.describe_rules(ListenerArn=livelistenerarn)
    
    print (b_tgp_response)
    print (l_tgp_response)

    for x in b_tgp_response['Rules']:
        if x['Priority'] == '1':
            b_target_group = x['Actions'][0]['TargetGroupArn']
    for x in l_tgp_response['Rules']:
        if x['Priority'] == '1':
            l_target_group = x['Actions'][0]['TargetGroupArn']

    b_id,b_sha = find_b_image_id(b_target_group)
    l_id, l_sha = find_b_image_id(l_target_group)

    return b_id,b_sha,l_id,l_sha

def find_b_image_id(targetgrouparn):
    #Returns the Docker image sha and tag value of the target group requested
 
    access=os.environ.get('AWS_ACCESS_KEY_ID_Target')
    secret=os.environ.get('AWS_SECRET_ACCESS_KEY_Target')
    session=os.environ.get('AWS_SESSION_TOKEN_Target')
    elb_client = boto3.client(
    'elbv2',
    aws_access_key_id=access,
    aws_secret_access_key=secret,
    aws_session_token=session,)
    response = elb_client.describe_tags(ResourceArns=[targetgrouparn])
    identifier = None
    imagesha = None
    for tags in response['TagDescriptions']:
        for tag in tags['Tags']:
            if tag['Key'] == "Identifier":
                print("Image identifier string on " + targetgrouparn + " : " + tag['Value'])
                identifier = tag['Value']
            if tag['Key'] == "Image":
                imagesha = tag['Value']
    return identifier,imagesha

def get_build_artifact_id(build_id):
    #We get the previous artifact from Codebuild by passing the execution id of the last build we got
    # with the funciton get_build_execution_id which contains the tag with the the Elastic Container Registry path
  
    codebuild_client = boto3.client('codebuild')
    response = codebuild_client.batch_get_builds(
        ids=[
            str(build_id),
        ]
    )
    for build in response['builds']:
        s3_location = build['artifacts']['location']
        bucketkey = s3_location.split(":")[5]
        bucket = bucketkey.split("/")[0]
        key = bucketkey[bucketkey.find("/") + 1:]
        s3_client = boto3.client('s3', config=Config(signature_version='s3v4'))
        s3_client.download_file(bucket, key, 'downloaded_object')
        zip_ref = zipfile.ZipFile('downloaded_object', 'r')
        zip_ref.extractall('downloaded_folder')
        zip_ref.close()
        with open('downloaded_folder/build.json') as data_file:
            objbuild = json.load(data_file)
        print(objbuild['tag'])
        return objbuild['tag']

def get_build_execution_id():
    #Get the execution id from the last build stage execution
   
    codepipeline_client = boto3.client('codepipeline')

    initiator = str(os.environ.get('CODEBUILD_INITIATOR')).split("/")[-1]
    response = codepipeline_client.get_pipeline_state(name=initiator)

    for stage in response['stageStates']:
        if stage['stageName'] == 'Build':
            for actionstate in stage['actionStates']:
                if actionstate['actionName'] == 'Build':
                    return actionstate['latestExecution']['externalExecutionId']

if __name__ == '__main__':
    handler()