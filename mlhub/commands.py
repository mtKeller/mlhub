#!/usr/bin/python3
#
# mlhub - Machine Learning Model Repository
#
# A command line tool for managing machine learning models.
#
# Copyright 2018 (c) Graham.Williams@togaware.com All rights reserved. 
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

import distro
import glob
import json
import logging
import mlhub.utils as utils
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.request
import uuid
import yaml

from distutils.version import StrictVersion
from mlhub.constants import (
    COMPLETION_SCRIPT,
    EXT_MLM,
    MLHUB_YAML,
    MLINIT,
    README,
)

# The commands are implemented here in a logical order with each
# command providing a suggesting of the following command.

# ------------------------------------------------------------------------
# AVAILABLE
# ------------------------------------------------------------------------


def list_available(args):
    """List the name and title of the models in the Hub."""

    # Setup.

    logger = logging.getLogger(__name__)
    logger.info('List available models.')
    logger.debug('args: {}'.format(args))

    meta, repo = utils.get_repo_meta_data(args.mlhub)
    model_names = [entry["meta"]["name"] for entry in meta]

    # Update bash completion list.

    utils.update_model_completion(set(model_names))

    # List model name only.

    if args.name_only:
        print('\n'.join(model_names))
        return

    # Provide some context.

    if not args.quiet:
        msg = "The repository '{}' provides the following models:\n"
        print(msg.format(repo))

    # List the meta data.

    for entry in meta:
        utils.print_meta_line(entry)

    # Suggest next step.
    
    if not args.quiet:
        utils.print_next_step('available')
        if not os.path.exists(MLINIT):
            print("Why not give the 'rain' model a go...\n\n"
                  "  $ ml install rain\n")

# ------------------------------------------------------------------------
# INSTALLED
# ------------------------------------------------------------------------


def list_installed(args):
    """List the installed models."""

    logger = logging.getLogger(__name__)
    logger.info('List installed models.')

    # Find installed models, ignoring special folders like R.

    if os.path.exists(MLINIT):
        msg = " in '{}'.".format(MLINIT)
        models = [f for f in os.listdir(MLINIT)
                  if os.path.isdir(os.path.join(MLINIT, f))
                  and f != "R"
                  and not f.startswith('.')
                  and not f.startswith('_')]
    else:
        msg = ". '{}' does not exist.".format(MLINIT)
        models = []

    models.sort()

    # Only list model names

    if args.name_only:
        print('\n'.join(models))
        return
        
    # Report on how many models we found installed.
        
    mcnt = len(models)
    plural = "s" if mcnt != 1 else ""
    print("Found {} model{} installed{}".format(mcnt, plural, msg))

    # Report on each of the installed models.
        
    if mcnt > 0:
        print("")

    invalid_models = []
    for p in models:
        try:
            entry = utils.load_description(p)
            utils.print_meta_line(entry)
        except (utils.DescriptionYAMLNotFoundException,
                utils.MalformedYAMLException,
                KeyError):
            mcnt -= 1
            invalid_models.append(p)
            continue

        # Update bash completion list.

        if 'commands' in entry:
            utils.update_command_completion(set(entry['commands']))

    invalid_mcnt = len(invalid_models)
    if invalid_mcnt > 0:
        print("\nOf which {} model package{} {} broken:\n".format(
            invalid_mcnt,
            's' if invalid_mcnt > 1 else '',
            'are' if invalid_mcnt > 1 else 'is'))
        print("  ====> \033[31m" + ', '.join(invalid_models) + "\033[0m")
        print(utils.get_command_suggestion('remove'))

    # Suggest next step.
    
    if not args.quiet:
        if mcnt > 0:
            utils.print_next_step('installed', scenario='exist')
        else:
            utils.print_next_step('installed', scenario='none')

# -----------------------------------------------------------------------
# INSTALL
# ------------------------------------------------------------------------


def install_model(args):
    """Install a model.

    Args:
        args: Command line args parsed by argparse.
        args.model (str): mlm/zip path, mlm/zip url, model name, GitHub repo,
                          like mlhubber/mlhub, or MLHUB.yaml on github repo,
                          like mlhubber/audit:doc/MLHUB.yaml.
    """

    logger = logging.getLogger(__name__)
    logger.info('Install a model.')
    logger.debug('args: {}'.format(args))

    model = args.model   # model pkg name
    url = args.model     # pkg file path or URL
    version = None       # model pkg version
    mlhubyaml = None     # MLHUB.yaml path or URL

    # Obtain the model URL if not a local file.

    if not utils.is_archive(model) and not utils.is_url(model) and '/' not in model:

        # Model package name, which can be found in mlhub repo.
        # Like:
        #     $ ml install audit
        #
        # We assume the URL got from mlhub repo is a link to a mlm/zip/tar file
        # or a GitHub repo URL.

        url, version, meta_list = utils.get_model_info_from_repo(model, args.mlhub)

        # Update bash completion list.

        utils.update_model_completion({e['meta']['name'] for e in meta_list})

    if not utils.is_archive(url):

        # Model from GitHub.
        # Like:
        #     $ ml install mlhubber/audit
        #     $ ml install mlhubber/audit:doc/MLHUB.yaml
        #     $ ml install https://github.com/mlhubber/audit/...

        mlhubyaml = utils.get_pkgyaml_github_url(url)  # URL to MLHUB.yaml
        url = utils.get_pkgzip_github_url(url)

    # Determine the path of downloaded/existing model package file

    pkgfile = "mlhubmodelpkg-" + str(uuid.uuid4().hex) + ".mlm"
    uncompressdir = pkgfile[:-4]  # Dir Where pkg file is extracted

    if utils.is_archive(url):
        pkgfile = os.path.basename(url)  # pkg file name
    elif utils.is_url(url):
        pkgfile = utils.get_url_filename(url)

    # Installation.

    entry = None     # Meta info read from MLHUB.yaml
    with tempfile.TemporaryDirectory() as mlhubtmpdir:

        # Determine the local path of the model package

        if utils.is_url(url):
            local = os.path.join(mlhubtmpdir, pkgfile)  # downloaded
        else:
            local = url  # local file path

        uncompressdir = os.path.join(mlhubtmpdir, uncompressdir)

        # Obtain model version.

        if version is None:
            if utils.ends_with_mlm(url):  # Get version number from MLM file name.

                model, version = utils.interpret_mlm_name(url)

            elif not utils.is_github_url(url):  # Get MLHUB.yaml inside the archive file.

                if utils.is_url(url):  # Download the file if needed
                    utils.download_model_pkg(url, local, args.quiet)

                utils.unpack_with_promote(local, uncompressdir)
                mlhubyaml = utils.get_available_pkgyaml(uncompressdir)  # Path to MLHUB.yaml

            if mlhubyaml is not None:  # Get version number from MLHUB.yaml
                entry = utils.read_mlhubyaml(mlhubyaml)
                meta = entry["meta"]
                model = meta["name"]
                version = meta["version"]

            utils.update_model_completion({model})  # Update bash completion list.

        # Check if model is already installed.

        install_path = os.path.join(utils.create_init(), model)  # Installation path
        if os.path.exists(install_path):
            installed_version = utils.load_description(model)['meta']['version']
            if StrictVersion(installed_version) > StrictVersion(version):
                yes = utils.yes_or_no(
                    "Downgrade '{}' from version '{}' to version '{}'",
                    model, installed_version, version, yes=True)
            elif StrictVersion(installed_version) == StrictVersion(version):
                yes = utils.yes_or_no(
                    "Replace '{}' version '{}' with version '{}'",
                    model, installed_version, version, yes=True)
            else:
                yes = utils.yes_or_no(
                    "Upgrade '{}' from version '{}' to version '{}'",
                    model, installed_version, version, yes=True)

            if not yes:
                sys.exit(0)
            else:
                print()

            shutil.rmtree(install_path)

        # Uncompress package file.

        if not os.path.exists(uncompressdir):  # Model pkg mlm file has not unzipped yet.
            if utils.is_url(url):  # Download the mlm file if needed.
                utils.download_model_pkg(url, local, args.quiet)

            utils.unpack_with_promote(local, uncompressdir)

        # Install package files.
        #
        # Because it is time-consuming to download all package files one-by-one , we
        # download the whole zipball from the repo first, then re-arrange the files
        # according to `dependencies` -> `files` in MLHUB.yaml if any.

        # Find if any files specified in MLHUB.yaml

        if mlhubyaml is None:  # mlm file
            mlhubyaml = utils.get_available_pkgyaml(uncompressdir)
            entry = utils.read_mlhubyaml(mlhubyaml)

        depspec = None
        if 'dependencies' in entry:
            depspec = entry['dependencies']
        elif 'dependencies' in entry['meta']:
            depspec = entry['meta']['dependencies']

        file_spec = None
        if depspec is not None and 'files' in depspec:
            file_spec = {'files': depspec['files']}
        elif 'files' in entry:
            file_spec = {'files': entry['files']}

        if file_spec is not None:  # install package files if they are specified in MLHUB.yaml

            # MLHUB.yaml should always be at the package root.

            os.mkdir(install_path)
            if utils.is_url(mlhubyaml):  # We currently only support MLHUB.yaml specified on GitHub.
                urllib.request.urlretrieve(
                    json.loads(urllib.request.urlopen(mlhubyaml).read())['download_url'],
                    os.path.join(install_path, MLHUB_YAML))
            else:
                shutil.move(mlhubyaml, install_path)

            # All package files except MLHUB.yaml should be specified in 'files' of MLHUB.yaml

            utils.install_file_deps(utils.flatten_mlhubyaml_deps(file_spec)[0][1],
                                    model,
                                    downloadir=uncompressdir)

        else:
            # Otherwise, put all files under package dir.
            # **Note** Here we must make sure <instal_path> does not exist.
            # Otherwise, <unzipdir> will be inside <install_path>
            shutil.move(uncompressdir, install_path)

        # Update bash completion list.

        utils.update_command_completion(set(utils.load_description(model)['commands']))

        if not args.quiet:

            # Informative message about the size of the installed model.

            print("Extracted '{}' into\n'{}' ({:,} bytes).".format(
                pkgfile, install_path, utils.dir_size(install_path)))

            # Suggest next step. README or DOWNLOAD

            utils.print_next_step('install', model=model)

# -----------------------------------------------------------------------
# DOWNLOAD
# ------------------------------------------------------------------------


def download_model(args):
    """Download the large pre-built model."""

    # TODO: Will this be a url in the DESCRIPTION file or will it be a
    # download.sh script. Which ever (maybe either), if it is present
    # then this command is available and will download the required
    # file, perhaps from the actual source of the model.
    
    model = args.model
   
    # Check that the model is installed.

    utils.check_model_installed(model)
    
    if not args.quiet:
        utils.print_next_step('download', model=model)

# ------------------------------------------------------------------------
# README
# ------------------------------------------------------------------------


def readme(args):
    """Display the model's README information."""

    # Setup.
    logger = logging.getLogger(__name__)

    model = args.model
    path = MLINIT + model
    readme_file = os.path.join(path, README)
    logger.info("Get README of {}.".format(model))

    # Check that the model is installed.

    utils.check_model_installed(model)
    
    # Display the README.

    if not os.path.exists(readme_file):  # Try to generate README from README.md
        readme_raw = readme_file[:readme_file.rfind('.')] + '.md'
        if not os.path.exists(readme_raw):
            readme_raw = readme_raw[:readme_raw.rfind('.')] + '.rst'
            if not os.path.exists(readme_raw):
                raise utils.ModelReadmeNotFoundException(model, readme_file)
        cmd = ("pandoc -t plain {} "
               "| awk '/^Usage$$/{{exit}}{{print}}' "
               "| perl -00pe0 > {}".format(readme_raw, README))
        proc = subprocess.Popen(cmd, shell=True, cwd=path, stderr=subprocess.PIPE)
        proc.communicate()
        if proc.returncode != 0:
            raise utils.ModelReadmeNotFoundException(model, readme_file)

    with open(readme_file, 'r') as f:
        print(utils.drop_newline(f.read()))

    # Suggest next step.

    if not args.quiet:
        utils.print_next_step('readme', model=model)

# ------------------------------------------------------------------------
# LICENSE
# ------------------------------------------------------------------------


def license(args):
    """Display the mode's LICENSE information."""

    print("Please assist by implementing this command.")
    
# -----------------------------------------------------------------------
# COMMANDS
# ------------------------------------------------------------------------


def list_model_commands(args):
    """ List the commands supported by this model."""

    # Setup.

    logger = logging.getLogger(__name__)
    model = args.model
    logger.info("List available commands of '{}'".format(model))

    # Check that the model is installed.

    utils.check_model_installed(model)
    
    info = utils.load_description(model)

    if args.name_only:
        print('\n'.join(list(info['commands'])))
        return
    
    msg = "The '{}' model "
    if 'title' not in info['meta']:
        title = None
    else:
        title = utils.lower_first_letter(utils.dropdot(info['meta']['title']))
        msg += "({}) "

    msg += "supports the following commands:"
    msg = msg.format(model, title)
    msg = textwrap.fill(msg, width=75)
    print(msg)

    for cmd in info['commands']:
        utils.print_model_cmd_help(info, cmd)

    # Update bash completion list.

    utils.update_command_completion(set(info['commands']))

    # Suggest next step.
    
    if not args.quiet:
        utils.print_next_step('commands', description=info, model=model)

# -----------------------------------------------------------------------
# CONFIGURE
# ------------------------------------------------------------------------


def configure_model(args):
    """Ensure the user's environment is configured."""

    # TODO: Add support for additional configuration if any except those
    #       specified in MLHUB.yaml.
    # TODO: When fail, print out the failed dep, as well as installed
    #       deps and non-installed deps.
    # TODO: Add support for specifying packages version.
    # TODO: Add more informative messages for different kinds of
    #       dependencies.

    # Other ideas for configuration
    #
    # 1 Construct mlhub container (from Ubuntu) with known starting point
    #
    # 2 Assume the user is on a DSVM with free Azure account to test out.
    #
    # 3 Read dependencies: and language: and then install as required:
    #
    # 4 Assume model packager provides a configure.R script. This is a
    #   override and no other configuration happens if this is
    #   supplied. Alternatively this is viewed as a cop-out prividing
    #   no support from mlhub for the model packager. The preference
    #   would be to use the dependencies: tag to list the required R
    #   or python packages.
    #
    # So the meta-code might be
    #
    #   if file.exists(configure.XX):
    #     XX configure.XX
    #   else if language: == "Rscript":
    #     packages <- dependencies:
    #     install  <- packages[!(packages %in% installed.packages()[,"Package"])]
    #     if(length(new.packages)) install.packages(install)
    #   else if language: == "python":
    #     packages = dependencies:
    #     cat pacakges > requirements.txt
    #     pip install -r requirements.txt
    #

    if not args.model:

        # Configure MLHUB per se.
        # Currently only bash completion.

        if distro.id() in ['debian', 'ubuntu']:
            path = os.path.dirname(__file__)
            commands = [
                'sudo install -m 0644 {} /etc/bash_completion.d'.format(COMPLETION_SCRIPT),
                'ml available > /dev/null',
                'ml installed > /dev/null', ]

            for cmd in commands:
                print('Executing: ', cmd)
                subprocess.run(cmd, shell=True, cwd=path, stderr=subprocess.PIPE)
                
            print("\nFor tab completion to take immediate effect:\n"
                  "\n  $ source /etc/bash_completion.d/ml.bash\n")

        return
    
    # Setup.
    
    model = args.model
    pkg_dir = utils.get_package_dir(model)
   
    # Check if the model package is installed.

    utils.check_model_installed(model)

    # Install dependencies specified in MLHUB.yaml

    entry = utils.load_description(model)
    depspec = None
    if 'dependencies' in entry:
        depspec = entry['dependencies']
    elif 'dependencies' in entry['meta']:
        depspec = entry['meta']['dependencies']

    if depspec is not None:
        for spec in utils.flatten_mlhubyaml_deps(depspec):
            category = spec[0][-1]
            deplist = spec[1]

            # Category include:
            #   ------------------------------------------------------------------------------
            #           category | action
            #   -----------------|------------------------------------------------------------
            #              None  |  install package according to entry['meta']['languages']
            #                    |  if R,      install.packages(xxx) from cran;
            #                    |  if Python, pip install xxx
            #   -----------------|------------------------------------------------------------
            #            system  |  apt-get install
            #                sh  |  apt-get install
            #   -----------------|------------------------------------------------------------
            #                 r  |  install.packages(xxx) from cran, version can be specified
            #              cran  |  install.packages(xxx) from cran, version can be specified
            #   cran-2018-12-01  |  install cran snapshot on 2018-12-01
            #            github  |  devtools::install_github from github
            #   -----------------|------------------------------------------------------------
            #            python  |  apt-get install python-xxx
            #           python3  |  apt-get install python3-xxx
            #               pip  |  pip install
            #              pip3  |  pip3 install
            #             conda  |  conda install
            #   -----------------|------------------------------------------------------------
            #             files  |  download files
            #   -----------------|------------------------------------------------------------

            # ----- Determine deps by language -----

            if category is None:

                lang = entry['meta']['languages'].lower()
                if lang == 'r':
                    utils.install_r_deps(deplist, model, source='cran')
                elif 'python'.startswith(lang):
                    utils.install_python_deps(deplist, source='pip')

            # ----- System deps -----

            elif category == 'system' or 'shell'.startswith(category):
                utils.install_system_deps(deplist)

            # ----- R deps -----

            elif category == 'r':
                utils.install_r_deps(deplist, model, source='cran')

            elif category == 'cran' or category == 'github' or category.startswith('cran-'):
                utils.install_r_deps(deplist, model, source=category)

            # ----- Python deps -----

            elif category.startswith('python') or category.startswith('pip') or category == 'conda':
                utils.install_python_deps(deplist, source=category)

            # ----- Files -----

            elif 'files'.startswith(category):
                utils.install_file_deps(deplist, model)

    # Run additional configure script if any.

    conf = utils.configure(pkg_dir, "configure.sh", args.quiet) or True
    conf = utils.configure(pkg_dir, "configure.R", args.quiet) or conf
    conf = utils.configure(pkg_dir, "configure.py", args.quiet) or conf

    if not conf:
        if depspec is not None:
            msg = ("No configuration script provided for this model. "
                   "The following dependencies are required:\n")
            print(msg)
            print(yaml.dump(depspec))
        else:
            print("No configuration provided (maybe none is required).")
            
    # Suggest next step.
    
    if not args.quiet:
        utils.print_next_step('configure', model=model)

# -----------------------------------------------------------------------
# DISPATCH
# ------------------------------------------------------------------------


def dispatch(args):
    """Dispatch other commands to the appropriate model provided script."""

    cmd = args.cmd
    model = args.model
    path = MLINIT + model

    param = " ".join(args.param)

    # Check that the model is installed.

    utils.check_model_installed(model)
    
    desc = utils.load_description(model)

    # Check if cmd needs to use graphic display indicated in DESCRIPTION.yaml.

    if 'display' in desc['meta'] and cmd in desc['meta']['display'] and os.environ.get('DISPLAY', '') == '':
        msg = "Graphic display is required but not available for command '{}'. Continue"
        yes = utils.yes_or_no(msg, cmd, yes=False)
        if not yes:
            msg = """
To enable DISPLAY be sure to connect to the server using 'ssh -X'
or else connect to the server's desktop using a local X server like X2Go.

"""
            sys.stdout.write(msg)
            sys.exit(1)

    # Obtain the default/chosen language for the package.

    lang = desc["meta"]["languages"]

    # Deal with malformed 'languages' field
    
    lang_opts = {"python": "py", "R": "R"}
    for k in list(lang_opts):
        if lang in k:
            lang = lang_opts[k]
            break
        
    # Obtain the specified script file.
    
    script = cmd + "." + lang

    logger = logging.getLogger(__name__)
    logger.debug("Execute the script: " + os.path.join(path, script))
     
    if cmd not in list(desc['commands']) or not os.path.exists(os.path.join(path, script)):
        raise utils.CommandNotFoundException(cmd, model)

    # Determine the interpreter to use
    #
    # .R => Rscript; .py => python, etc.

    interpreter = utils.interpreter(script)

    # _MLHUB_CMD_CWD: a environment variable indicates current working
    #          directory where command `ml xxx` is invoked.
    # _MLHUB_MODEL_NAME: env variable indicates the name of the model.
    # 
    # The above two env vars can be obtained by helper function, such
    # as utils.get_cmd_cwd().  And model package developer should be
    # use the helper function instead of the env vars directly.

    command = "export _MLHUB_CMD_CWD='{}'; export _MLHUB_MODEL_NAME='{}'; {} {} {}".format(
        os.getcwd(), model, interpreter, script, param)

    logger.debug("(cd " + path + "; " + command + ")")

    proc = subprocess.Popen(command, shell=True, cwd=path, stderr=subprocess.PIPE)
    output, errors = proc.communicate()
    if proc.returncode != 0:
        errors = errors.decode("utf-8")

        # Check if it is Python dependency unsatisfied

        dep_required = re.compile(r"ModuleNotFoundError: No module named '(.*)'").search(errors)

        # Check if R dependency unsatisified

        if dep_required is None:
            dep_required = re.compile(r"there is no package called ‘(.*)’").search(errors)

        # Check if required data resource not found

        data_required = re.compile(r"mlhub.utils.DataResourceNotFoundException").search(errors)

        if dep_required is not None:  # Dependency unsatisfied
            dep_required = dep_required.group(1)
            logger.error("Dependency unsatisfied: {}\n{}".format(dep_required, errors))
            raise utils.LackDependencyException(dep_required, model)
        elif data_required is not None:  # Data not found
            raise utils.DataResourceNotFoundException()
        else:  # Other unknown errors
            print("An error was encountered:\n")
            print(errors)

    else:
        # Suggest next step

        if not args.quiet:
            utils.print_next_step(cmd, description=desc, model=model)
    
# ------------------------------------------------------------------------
# DONATE
# ------------------------------------------------------------------------


def donate(args):
    """Consider a donation to the author."""

    print("Please assist by implementing this command: support donations to the author.")
    
# ------------------------------------------------------------------------
# CLEAN
# ------------------------------------------------------------------------


def remove_mlm(args):
    """Remove downloaded {} files.""".format(EXT_MLM)

    mlm = glob.glob(os.path.join(MLINIT, "*.mlm"))
    mlm.sort()
    for m in mlm:
        if utils.yes_or_no("Remove model package archive '{}'", m, yes=True):
            os.remove(m)

# ------------------------------------------------------------------------
# REMOVE
# ------------------------------------------------------------------------


def remove_model(args):
    """Remove installed model."""

    # Setup.
    
    model = args.model
    path = MLINIT
    cache = None
    if model is None:
        if os.path.exists(MLINIT):
            msg = "*Completely* remove all installed models in '{}'"
        else:
            msg = "The local model folder '{}' does not exist. Nothing to do."
            msg = msg.format(MLINIT)
            print(msg)
            return
    else:
        path = os.path.join(path, model)
        if os.path.exists(utils.get_package_cache_dir(model)):
            cache = utils.get_package_cache_dir(model)
        msg = "Remove '{}'"
        
        # Check that the model is installed.

        utils.check_model_installed(model)

    if utils.yes_or_no(msg, path, yes=True):
        shutil.rmtree(path)
        if cache is not None and utils.yes_or_no("Remove cache '{}' as well", cache, yes=False):
            shutil.rmtree(cache)
    else:
        if model is None and not args.quiet:
            utils.print_next_step('remove')
