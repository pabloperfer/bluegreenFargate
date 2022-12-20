from __future__ import print_function
import json
import boto3
import sys
import traceback

code_pipeline = boto3.client('codepipeline')
#We send the codepipeline the signal of a job that ended correctly passing the job id and a message
def put_job_success(job, message):
    print('success')
    print(message)
    code_pipeline.put_job_success_result(jobId=job)
def put_job_failure(job, message):
    #We send the codepipeline the signal of a job that did not end as expected passing the job id and a message.
    
    print('failure')
    print(message)
    code_pipeline.put_job_failure_result(jobId=job, failureDetails={'message': message, 'type': 'JobFailed'})
#we tell the pipeline to invoke the function again if needed
def continue_job_later(job, message):
    # This token allows the action to continue and the function to succeed even if it exceeds a fifteen-minute runtime
    continuation_token = json.dumps({'previous_job_id': job})

    print('continuation')
    print(message)
    code_pipeline.put_job_success_result(jobId=job, continuationToken=continuation_token)
#we get the pipeline job id and the data of the job
def get_user_params(job_id,job_data):
    try:
        user_parameters = job_data['actionConfiguration']['configuration']['UserParameters']
        decoded_parameters = json.loads(user_parameters)
        print(decoded_parameters)
    except Exception as e:
        put_job_failure(job_id,e)
        raise Exception('could not be decoded')
    return decoded_parameters

#gets the production target group and non-production target group and their listeners and swaps the rule of the listeners to redirect the traffic
def swaptargetgs(elbname,assume_role_arn):
    sts_connection = boto3.client('sts')
    acct_b = sts_connection.assume_role(RoleArn=assume_role_arn,RoleSessionName="cross_acct_lambda") 
    ACCESS_KEY = acct_b['Credentials']['AccessKeyId']
    SECRET_KEY = acct_b['Credentials']['SecretAccessKey']
    SESSION_TOKEN = acct_b['Credentials']['SessionToken']
    elbclient = boto3.client('elbv2',
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    aws_session_token=SESSION_TOKEN,)

    elbresponse = elbclient.describe_load_balancers(Names=[elbname])

    print(elbresponse)

    listners = elbclient.describe_listeners(LoadBalancerArn=elbresponse['LoadBalancers'][0]['LoadBalancerArn'])
    print (listners)

    for x in listners['Listeners']:
        if (x['Port'] == 443):
            llistenerarn = x['ListenerArn']
        if (x['Port'] == 8443):
            blistenerarn = x['ListenerArn']

    ltgresponse = elbclient.describe_rules(ListenerArn=llistenerarn)

    print (ltgresponse)
    for x in ltgresponse['Rules']:
        if x['Priority'] == '1':
            ltargetgr = x['Actions'][0]['TargetGroupArn']
            liverulearn = x['RuleArn']

    btgresponse = elbclient.describe_rules(ListenerArn=blistenerarn)

    for x in btgresponse['Rules']:
        if x['Priority'] == '1':
            btargetgr = x['Actions'][0]['TargetGroupArn']
            brulearn = x['RuleArn']
    print("Live=" + ltargetgr)
    print("Beta=" + btargetgr)

    modifyB = elbclient.modify_rule(
        RuleArn=brulearn,
        Actions=[
            {
                'Type': 'forward',
                'TargetGroupArn': ltargetgr
            }])

    print(modifyB)
    modifyL = elbclient.modify_rule(
        RuleArn=liverulearn,
        Actions=[
            {
                'Type': 'forward',
                'TargetGroupArn': btargetgr
            }] )
    print(modifyL)
    modify_tags(ltargetgr,"IsProduction","False",assume_role_arn)
    modify_tags(btargetgr, "IsProduction", "True",assume_role_arn)

#update tag on each target group with a tag key isproduction and a boolean value after the swap was done.
def modify_tags(arn,tagkey,tagvalue,assume_role_arn):
    sts_connection = boto3.client('sts')
    acct_b = sts_connection.assume_role(RoleArn=assume_role_arn,RoleSessionName="cross_acct_lambda") 
    ACCESS_KEY = acct_b['Credentials']['AccessKeyId']
    SECRET_KEY = acct_b['Credentials']['SecretAccessKey']
    SESSION_TOKEN = acct_b['Credentials']['SessionToken']
    elbclient = boto3.client('elbv2',
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    aws_session_token=SESSION_TOKEN,)
    
    elbclient.add_tags(
        ResourceArns=[arn],
        Tags=[
            {
                'Key': tagkey,
                'Value': tagvalue
            },])
#Lambda function invokes this handler getting from the event information about the pipeline and the parameters from the input like the alb name.
def handler(event, context):
    try:
        print(event)
        job_id = event['CodePipeline.job']['id']
        job_data = event['CodePipeline.job']['data']
        params = get_user_params(job_id,job_data)
        elb_name = params['ElbName']
        print("ELBNAME="+elb_name)
        assume_role_arn = params['assume_role_arn']
        swaptargetgs(elb_name,assume_role_arn)
        put_job_success(job_id,"Target Group Swapped.")
    except Exception as e:
        print('exception triggered')
        print(e)
        traceback.print_exc()
        put_job_failure(job_id, ' exception: ' + str(e))
    print('Execution complete.')
    return "Complete."

if __name__ == "__main__":
    handler(sys.argv[0], None)