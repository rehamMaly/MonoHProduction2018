#Script to submit steps 1 through 3 through crab
#Reads crab_log.json file generated by craba.py from previous step to determine what to submit

#To do: fix naming of datasets so output dataset isn't ..._step1_HZZ_step2_HZZ_step3_HZZ

from WMCore.Configuration import Configuration
from CRABAPI.RawCommand import crabCommand as crab
from crab_blacklist import blacklist
import os,re

import argparse

parser=argparse.ArgumentParser()
parser.add_argument('step',type=int,help='Step to submit')
parser.add_argument('year',type=int,help='Year to submit jobs for.')
parser.add_argument('--continue','-c',dest='continue_',action='store_true',help='Continue after submission failure.')
parser.add_argument('--fake_submit','-f',action='store_true',help="Don't really submit to server. Useful for testing script.")
parser.add_argument('--skip','-s',action='store_true',help='Skip jobs from a previous stage that are unfinished, without prompting.')
args=parser.parse_args()

validate_taskname=re.compile(r"^[a-zA-Z0-9\-_:]{1,100}$")

step=args.step
year=args.year

if not year in [2016,2018]:
    raise ValueError('Not supported for year %i.' % year)

if step > 3 or step < 1:
    raise ValueError('Invalid step %i' % step)

if args.fake_submit:
    #Runs through the motions of submitting, but does not submit anything to server
    import CRABClient.Commands.submit
    from submit_test import submit
    from CRABClient.JobType.CMSSWConfig import configurationCache
    CRABClient.Commands.submit.submit=submit

last_step=step-1
step='step%i' % step

continue_after_failure=args.continue_

print 'Preparing to submit jobs for step %i' % (last_step+1)

#Setup basic config
def get_config(dataset,inputDataset):
    dataset=dataset.split('_HZZ')[0].split('_step')[0] #Chop off _step*_HZZ from the dataset, so we don't have _step1_HZZ_step2_HZZ_step3_HZZ by the end
    dataset=dataset.encode('utf-8')
    config = Configuration()
    config.section_("General")
    config.General.transferLogs = True
    suffix='_%s_HZZ' % step
    request_name=dataset+suffix
    #Check request name. If it fails, try truncating the dataset name
    if not validate_taskname.match(request_name):
        request_name=dataset[0:(100-len(suffix))]
        request_name+=suffix
    #if it still doesn't validate, fall back to default
    if validate_taskname.match(request_name):
        config.General.requestName = str(request_name)
    config.General.workArea = 'MonoHProduction_%i_%s' % (year,step)
    if args.fake_submit:
        config.General.workArea = 'FakeSubmit_%s' % step
    
    config.section_("JobType")
    config.JobType.pluginName  = 'Analysis'
    config.JobType.psetName = '%s_%i.py' % (step,year)
    config.JobType.numCores = 8
    config.JobType.maxMemoryMB = 8000
    config.JobType.allowUndistributedCMSSW = True

    config.section_("Data")
    config.Data.splitting = 'FileBased'
    config.Data.unitsPerJob = 1
    config.Data.outputDatasetTag = '%s_%s_HZZ_%i' % (dataset,step,year)
    config.Data.inputDBS = 'phys03'
    config.Data.publication = True
    config.Data.inputDataset = inputDataset

    config.section_("Site")
    config.Site.storageSite = 'T2_US_Wisconsin'
    config.Site.whitelist=['T2_US_*']
    config.Site.blacklist=blacklist
    return config 

import pickle, glob, json

json_file='MonoHProduction_%i_step%i/crab_log.json' % (year,last_step)
try:
    with open(json_file) as f:
        js=json.load(f)
except IOError as e:
    import errno
    if e[0]==errno.ENOENT:
        print 'No such file "%s". Make sure to run `craba.py status` in the directory "%s" before running this script.' % (json_file,json_file.rsplit('/',1)[0])
        raise SystemExit
    else:
        raise

config_dict={}

def confirm(message):
    try:
        cont=raw_input('%s (y/n) ' % message).lower()
        if cont[0]=='q': raise KeyboardInterrupt
        if cont in ['y','yes','you betcha','yep','yup','yeah','yes please','please','please do','you\'re darn tootin\'']:
            return True
        elif cont[0]=='y':
            print 'Pardon?'
            return confirm(message)
        else:
            return False
    except KeyboardInterrupt:
        print 'Exiting.'
        raise SystemExit
#For parsing the output dataset (which is a string in the form of a python list) without running eval
import ast
for key,info in js.items():
    try:
        outdataset=ast.literal_eval(info['outdatasets'])
    except KeyError:
        print 'Error parsing key %s' % key
        print 'Info: ',info
        continue
    except ValueError:
        if info['outdatasets'] is None:
            print 'Dataset %s has no publication information available. Skipping.' % key
            continue
        print 'Failed to parse string',info['outdatasets'],'for dataset',key
        raise SystemExit
    if(len(outdataset)!=1): 
        raise ValueError('Too many output datasets.') #Not sure how this can even happen, so figure it out if it ever does
    outdataset=outdataset[0]
    dataset=outdataset.split('/')[2].split('-',1)[1].rsplit('-',1)[0]
    status=info['jobsPerStatus']
    if status.keys()!=['finished']:
        print 'Job not finished for %s. Skipping.' % dataset
        print 'Status:',status
        if args.skip or not confirm('Submit anyway?'):
            continue
    number_of_jobs=status['finished']
    publication=info['publication']
    if(publication!={'done':number_of_jobs}):
        print 'Publication not finished for %s. Skipping.' % dataset
        print 'Status:',publication
        if args.skip or not confirm('Submit anyway?'):
            continue
    config=get_config(dataset,outdataset)
    output_dir=os.path.join(config.General.workArea,'crab_%s' % config.General.requestName)
    if os.path.exists(output_dir):
        #Don't offer to submit anyway or you have to enter "Y" many times to try submitting failed jobs again
        print 'Crab directory for dataset %s already submitted. Skipping.' % dataset
        print 'If this job should be resubmitted, kill it and remove the directory, then run this script again.'
        continue
    if os.path.exists(output_dir.rstrip('/')+'_FAILED'):
        #Failed directories
        print 'Failed submission for dataset %s exists. Please handle this (and any other failed submissions) before continuing to submit.' % dataset
        raise SystemExit
    config_dict[dataset]=config
number_of_jobs=len(config_dict)
if number_of_jobs > 0:
    print 'Will attempt to submit %i jobs.' % len(config_dict)
else:
    print 'No jobs to submit.'
    raise SystemExit
if not confirm('Continue?'):
    print 'Exiting.'
    raise SystemExit

print 'Beginning submission.'
failed_submissions=[]
pyCfgDataset=None

#Use to change parameters of CMSSW config between submissions without forking
#Skips the slow import of CMSSW config for subsequent jobs running over the same file with same pyCfgParams
#(Only usable in cases where pyCfgParams does not need to be different between each run)
from CRABClient.JobType.CMSSWConfig import configurationCache
#Give output for failed submissions
import traceback
#If continuing after failure, still don't continue if the *first* submission fails
success=False
try:
    for dn,config in config_dict.iteritems():
        try:
            output_file='file:%s_%s.root' % (dn,step)
            if not pyCfgDataset:
                pyCfgDataset='outputFile=%s' % output_file
                #Set output filename in pyCfgParams
                config.JobType.pyCfgParams=[pyCfgDataset]
            else:
                #Set the pyCfgParams to be the same so that crab will not complain (we will be overwriting this in the next line anyway)
                config.JobType.pyCfgParams=[pyCfgDataset]
                #Set output filename directly in the pset
                imported_pset_process=configurationCache.values()[0]['config'].process
                if step=='step1':
                    imported_pset_process.PREMIXRAWoutput.fileName=output_file
                elif step=='step2':
                    imported_pset_process.AODSIMoutput.fileName=output_file
                elif step=='step3':
                    imported_pset_process.MINIAODSIMoutput.fileName=output_file
            print 'Submitting for dataset %s' % dn
            crab('submit',config=config)
            success=True
        except Exception as e:
            failed_submissions.append(config)
            if success and continue_after_failure:
                print 'Failed submission for dataset %s. Traceback follows:' % dataset
                traceback.print_exc()
            else:
                print 'Fatal error. Failed submission for dataset %s. Traceback follows:' % dataset
                traceback.print_exc()
                raise SystemExit
finally: #Do this even if interrupted
    if failed_submissions:
        print '%i submissions failed. Appending "FAILED" to directories. Please check that these jobs did not in fact submit and then remove the directories, or rename them if the submission was successful.' % len(failed_submissions)
        import shutil
        for config in failed_submissions:
            output_dir=os.path.join(config.General.workArea,'crab_%s' % config.General.requestName)
            print output_dir
            try:
                shutil.move(output_dir,output_dir+'_FAILED')
            except:
                print 'Failed to move directory %s' % output_dir
