import argparse
import getpass
import os
from pathlib import Path
from .organizations import Registry

def main():
    parser=argparse.ArgumentParser(description="Provision a private Building Brain pilot organization")
    parser.add_argument("name")
    parser.add_argument("email")
    args=parser.parse_args()
    password=getpass.getpass("Owner password: ")
    if password != getpass.getpass("Confirm password: "):
        parser.error("Passwords do not match")
    data=Path(os.environ.get("DATA_DIR",str(Path(__file__).resolve().parent.parent/"data")))
    oid,_=Registry(data/"identity").create_organization(args.name,args.email,password)
    print("Organization ID:",oid)

if __name__=="__main__":
    main()
