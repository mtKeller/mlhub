#!/usr/bin/python3
#
# mlhub - Machine Learning Model Repository
#
# A command line tool for managing machine learning models.
#
# Copyright 2018-2019 (c) Graham.Williams@togaware.com All rights reserved. 
#
# This file is part of mlhub.
#
# MIT License
#
# Permission is hereby granted, free of charge, to any person obtaining a copy 
# of this software and associated documentation files (the ""Software""), to deal 
# in the Software without restriction, including without limitation the rights 
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell 
# copies of the Software, and to permit persons to whom the Software is 
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in 
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED *AS IS*, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR 
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, 
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE 
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER 
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, 
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN 
# THE SOFTWARE.

import json
import os
import sys
import requests
import termios
import tty

# ----------------------------------------------------------------------
# Support Package Developers
# ----------------------------------------------------------------------

# Load subscription key and endpoint from file.

def load_key(path):
    key = None
    endpoint = None
    markchar = "'\" \t"
    with open(path, 'r') as file:
        for line in file:
            line = line.strip('\n')
            pair = line.split('=')
            if len(pair) == 2:
                k = pair[0].strip(markchar).lower()
                v = pair[1].strip(markchar)
                if k == 'key':
                    key = v
                elif k == 'endpoint':
                    endpoint = v
            elif not line.startswith('#'):
                line = line.strip(markchar)
                if line.startswith('http'):
                    endpoint = line
                else:
                    key = line
    return key, endpoint

# Either load key/endpoint from file or ask user and save to file.

def azkey(key_file, service="Cognitive Services"):
    """The user is asked for an Azure subscription key and endpoint. The
    provided information is saved into a file for future use. The
    contents of that file is the key and endpoint with the endpoint
    identified as starting with http:

    a14d1234abcda4f2f6e9f565df34ef24
    https://westus2.api.cognitive.microsoft.com/

    """

    key = None

    # Set up messages.
    
    prompt_key = "Please paste your {} subscription key: ".format(service)
    prompt_endpoint = "Please paste your endpoint: "

    msg_request = """\
An Azure resource is required to access this service (and to run this command).
See the README for details of a free subscription. If you have a subscription
then please paste the key and the endpoint here.
"""
    msg_found = """\
The following file has been found and is assumed to contain an Azure 
subscription key and endpoint for {}. We will load 
the file and use this information.

    {}
""".format(service, key_file)

    msg_saved = """
I've saved that information into the file:

    {}
""".format(key_file)

    # Obtain the key/endpoint.
    
    if os.path.isfile(key_file) and os.path.getsize(key_file) > 0:
        print(msg_found)
        key, endpoint = load_key(key_file)
    else:
        print(msg_request)
        
        key      = ask_password(prompt_key)
        endpoint = input(prompt_endpoint)

        if len(key) > 0 and len(endpoint) > 0:
            ofname = open(key_file, "w")
            ofname.write("{}\n{}\n".format(key, endpoint))
            ofname.close()
            print(msg_saved)

    return key, endpoint

# Simple input of password.

def ask_password(prompt=None):
    """Echo '*' for every input character. Only implements the basic I/O
    functionality and so only Backspace is supported.  No support for
    Delete, Left key, Right key and any other line editing.

    Reference: https://mail.python.org/pipermail/python-list/2011-December/615955.html
    """

    symbol = "`~!@#$%^&*()-_=+[{]}\\|;:'\",<.>/?"
    if prompt:
        sys.stdout.write(prompt)
        sys.stdout.flush()

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    chars = []
    try:
        tty.setraw(sys.stdin.fileno())
        while True:
            c = sys.stdin.read(1)
            if c in '\n\r':  # Enter.
                break
            if c == '\003':
                raise KeyboardInterrupt
            if c == '\x7f':  # Backspace.
                if chars:
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
                    del chars[-1]
                continue
            if c.isalnum() or c in symbol:
                sys.stdout.write('*')
                sys.stdout.flush()
                chars.append(c)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write('\n')

    return ''.join(chars)

# Send a request.


def azrequest(endpoint, url, subscription_key, request_data):
    """Send anomaly detection request to the Anomaly Detector API. 

    If the request is successful, the JSON response is returned.

    Aim to generailse this to go into MLHUB to send request.
    """
    
    headers = {'Content-Type': 'application/json',
               'Ocp-Apim-Subscription-Key': subscription_key}
    
    response = requests.post(os.path.join(endpoint, url),
                             data=json.dumps(request_data),
                             headers=headers)
    
    if response.status_code == 200:
        return json.loads(response.content.decode("utf-8"))
    else:
        print(response.status_code)
        raise Exception(response.text)

def mlask(begin=""):
    print(begin + "Press Enter to continue: ", end="")
    answer = input()

def mlcat(title="", text="", delim="=", begin="", end="\n"):
    sep = delim*len(title) + "\n" if len(title) > 0 else ""
    ttl_sep = "\n" if len(title) > 0 else ""
    print(begin + sep + title + ttl_sep + sep + ttl_sep + text, end=end)

