#!/usr/bin/env python
# Must be the first line
from __future__ import print_function
import urllib3

import sys
import json
import boto3
import time

VERBOSE = 1
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_regions(client):
  """ Build a region list """

  reg_list = []
  regions = client.describe_regions()
  data_str = json.dumps(regions)
  resp = json.loads(data_str)
  region_str = json.dumps(resp['Regions'])
  region = json.loads(region_str)
  for reg in region:
    reg_list.append(reg['RegionName'])
  return reg_list

def get_default_vpcs(client):
  vpc_list = []
  vpcs = client.describe_vpcs(
    Filters=[
      {
          'Name' : 'isDefault',
          'Values' : [
            'true',
          ],
      },
    ]
  )
  vpcs_str = json.dumps(vpcs)
  resp = json.loads(vpcs_str)
  data = json.dumps(resp['Vpcs'])
  vpcs = json.loads(data)
  
  for vpc in vpcs:
    tags = {tag['Key']: tag['Value'] for tag in vpc.get('Tags', [])}
    vpc_name = tags.get('Name', 'No name')
    vpc_list.append((vpc['VpcId'], vpc_name))
  
  return vpc_list

def describe_nics(ec2, vpcid):
  nics = ec2.describe_network_interfaces(
    Filters=[
      {"Name": "vpc-id", "Values": [vpcid]}
    ]
  )

  return nics['NetworkInterfaces']

def del_igw(ec2, vpcid):
  """ Detach and delete the internet-gateway """
  vpc_resource = ec2.Vpc(vpcid)
  igws = vpc_resource.internet_gateways.all()
  if igws:
    for igw in igws:
      try:
        print("Detaching and Removing igw-id: ", igw.id) if (VERBOSE == 1) else ""
        igw.detach_from_vpc(
          VpcId=vpcid
        )
        igw.delete(
          # DryRun=True
        )
      except Exception as e:
        raise e

def del_sub(ec2, vpcid):
  """ Delete the subnets """
  vpc_resource = ec2.Vpc(vpcid)
  subnets = vpc_resource.subnets.all()
  default_subnets = [ec2.Subnet(subnet.id) for subnet in subnets if subnet.default_for_az]
  
  if default_subnets:
    try:
      for sub in default_subnets: 
        print("Removing sub-id: ", sub.id) if (VERBOSE == 1) else ""
        sub.delete(
          # DryRun=True
        )
    except Exception as e:
      raise e

def del_rtb(ec2, vpcid):
  """ Delete the route-tables """
  vpc_resource = ec2.Vpc(vpcid)
  rtbs = vpc_resource.route_tables.all()
  if rtbs:
    try:
      for rtb in rtbs:
        assoc_attr = [rtb.associations_attribute for rtb in rtbs]
        if [rtb_ass[0]['RouteTableId'] for rtb_ass in assoc_attr if rtb_ass[0]['Main'] == True]:
          print(rtb.id + " is the main route table, continue...")
          continue
        print("Removing rtb-id: ", rtb.id) if (VERBOSE == 1) else ""
        table = ec2.RouteTable(rtb.id)
        table.delete(
          # DryRun=True
        )
    except Exception as e:
      raise e

def del_acl(ec2, vpcid):
  """ Delete the network-access-lists """
  
  vpc_resource = ec2.Vpc(vpcid)      
  acls = vpc_resource.network_acls.all()

  if acls:
    try:
      for acl in acls: 
        if acl.is_default:
          print(acl.id + " is the default NACL, continue...")
          continue
        print("Removing acl-id: ", acl.id) if (VERBOSE == 1) else ""
        acl.delete(
          # DryRun=True
        )
    except Exception as e:
      raise e

def del_sgp(ec2, vpcid):
  """ Delete any security-groups """
  vpc_resource = ec2.Vpc(vpcid)
  sgps = vpc_resource.security_groups.all()
  if sgps:
    try:
      for sg in sgps: 
        if sg.group_name == 'default':
          print(sg.id + " is the default security group, continue...")
          continue
        print("Removing sg-id: ", sg.id) if (VERBOSE == 1) else ""
        sg.delete(
          # DryRun=True
        )
    except Exception as e:
      raise e

def del_vpc(ec2, vpcid):
  """ Delete the VPC """
  vpc_resource = ec2.Vpc(vpcid)
  try:
    print("Removing vpc-id: ", vpc_resource.id)
    vpc_resource.delete(
      # DryRun=True
    )
  except Exception as e:
      print("Please remove dependencies and delete VPC manually.")
      raise e

def main():
  # List of account names to delete default vpcs of
  # There must be an aws profile_name matching each of these account names
  account_names = [
    "account_name"
  ]
  dry_run = True # Change this to true to check for regions and nics in those regions

  print(f'DryRun: {dry_run}. Sleeping for 5s')
  time.sleep(5)

  successful_accounts = []
  unsuccessful_accounts = {}

  for account_name in account_names:
    output = delete_default_vpcs(account_name, dry_run)
    if output == 'Success':
      successful_accounts.append(account_name)
    else:
      unsuccessful_accounts[account_name] = output
  
  # Print outputs
  print('\n')
  print(f'Full Deletions {len(successful_accounts)}/{len(account_names)}')
  if len(unsuccessful_accounts) != 0:
    print(f'\nUnsuccessful accounts')
    for k, v in unsuccessful_accounts.items():
      print(f'\t{k}: {v}')

    

# delete_default_vpcs takes an account name (also used for profile_name) and a dry run boolean and returns a status string
# of what happened when trying to delete the default vpcs, whether it was successful or not
def delete_default_vpcs(account_name, dry_run=True):
  print(f'\n*** Deleting Default VPCs for {account_name} - DryRun={dry_run} ***')
  try:
    session = boto3.Session(profile_name=account_name)
  except Exception as e:
    return f'Error establishing session {e}'


  """
  Do the work - order of operation
  1.) Delete the internet-gateway
  2.) Delete subnets
  3.) Delete route-tables
  4.) Delete network access-lists
  5.) Delete security-groups
  6.) Delete the VPC 
  """

  try:
    client = session.client('ec2', verify=False)
    regions = get_regions(client)
  except Exception as e:
      return f'Error creating clients {e}'

  sleep_time = 1 
  for region in regions:
    print(f'Region {region}')

    try:
      ec2 = session.resource('ec2', region_name = region, verify=False)
      client = session.client('ec2', region_name = region, verify=False)
      vpcs = get_default_vpcs(client)
      print(f'Got {len(vpcs)} default vpcs')

    except Exception as e:
      return f'Error getting vpcs {e}'

    else:
      for vpc in vpcs:
        print("\n" + "\n" + "REGION:" + region + "\n" + "VPC Id:" + vpc[0] + "\n" + "VPC Name:" + vpc[1])

        try:
          nics = describe_nics(client, vpc[0])
        except Exception as e:
          return f'Error getting nics {e}'

        for nic in nics:
          print('VPC ID: ' + vpc[0] + " -- NIC: " + nic['NetworkInterfaceId'])

        if len(nics) != 0:
          print('TOO MANY NICS FOR VPC, CANT DELETE')
          continue

        
        if dry_run:
          print(f'DryRun={dry_run}. Would delete, skipping...') 
        else:
          print(f'DryRun={dry_run}. Deleting resources...')
          try:
            print("deleting igw")
            del_igw(ec2, vpc[0])
            time.sleep(sleep_time)
            
            print("deleting subs")
            del_sub(ec2, vpc[0])
            time.sleep(sleep_time)
          
            print("deleting rtbs")
            del_rtb(ec2, vpc[0])
            time.sleep(sleep_time)
            
            print("deleting acls")
            del_acl(ec2, vpc[0])
            time.sleep(sleep_time)
            
            print("deleting sgs")
            del_sgp(ec2, vpc[0])
            time.sleep(sleep_time)
            
            print("deleting vpc")
            del_vpc(ec2, vpc[0])
          except Exception as e:
            return f'Error deleting things {e}'
        
        return 'Success'

if __name__ == "__main__":
  main()
