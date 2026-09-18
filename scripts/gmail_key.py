"""Create a local encryption key once. Never print it or include it in Git."""
import argparse
import os
from cryptography.fernet import Fernet

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    args=parser.parse_args()
    fd=os.open(args.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream: stream.write(Fernet.generate_key())
    print('Encryption key created with owner-only permissions.')
