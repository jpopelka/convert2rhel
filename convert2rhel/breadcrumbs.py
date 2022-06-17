# -*- coding: utf-8 -*-
#
# Copyright(C) 2021 Red Hat, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import json
import os
import re
import sys

from datetime import datetime

from six.moves import zip_longest

from convert2rhel import pkghandler, systeminfo


FILE = "/etc/migration-results"


class Breadcrumbs(object):
    """The so-called breadcrumbs data is a collection of basic information about the convert2rhel execution.

    This data is to be stored in a specific file in a machine-readable format which can be collected by various
    tools like sosreport or Red Hat Insights for further analysis.
    """

    def __init__(self):
        self.activity = "conversion"
        # Version of the JSON schema of the breadcrumbs file. To be changed when the JSON schema changes.
        self.version = "1"
        # The convert2rhel command as executed by the user including all the options.
        self.executed = "null"
        # NEVRA = Name, Epoch, Version, Release, Architecture
        self.nevra = "null"
        # The convert2rhel package signature as stored in the RPM DB.
        self.signature = "null"
        # A boolean indicating whether the conversion stopped before successfully converting the system or not.
        self.success = "null"
        self.activity_started = "null"
        self.activity_ended = "null"
        self.source_os = "null"
        self.target_os = "null"
        # Convert2RHEL-related environment variables used while executing convert2rhel (CONVERT2RHEL_*).
        self.env = {}
        # Run ID is to be populated by Leapp only. The value should be null in the json generated by convert2rhel.
        self.run_id = "null"
        # The convert2rhel package object from the yum/dnf python API for further information extraction.
        self._pkg_object = None

    def collect_early_data(self):
        """Set data which is accessible before the conversion"""
        self._set_pkg_object()
        self._set_executed()
        self._set_nevra()
        self._set_signature()
        self._set_source_os()
        self._set_started()

    def finish_success(self):
        """Set data accessible after successfully conversion and generate the JSON file."""
        self._set_target_os()
        self._set_success_ok()
        self._set_ended()
        self._generate_json()

    def finish_fail(self):
        """Generate the JSON recording the conversion failure."""
        self._set_success_fail()
        self._set_ended()
        self._generate_json()

    def _set_pkg_object(self):
        """Set pkg_object which is used to get information about installed Convert2RHEL"""
        # the index position is there because get_installed_pkg_objects return list, which is filtered and
        # should contain just one item
        self._pkg_object = pkghandler.get_installed_pkg_objects(name="convert2rhel")[0]

    def _set_executed(self):
        """Set how was Convert2RHEL executed"""
        cli_options_to_sanitize = frozenset(("--password", "-p", "--activationkey", "-k"))
        self.executed = sanitize_cli_options(sys.argv, cli_options_to_sanitize)

    def _set_nevra(self):
        """Set NEVRA of installed Convert2RHEL"""
        self.nevra = pkghandler.get_pkg_nevra(self._pkg_object)

    def _set_signature(self):
        """Set signature of installed Convert2RHEL"""
        self.signature = pkghandler.get_pkg_signature(self._pkg_object)

    def _set_source_os(self):
        self.source_os = systeminfo.SystemInfo._get_system_release_file_content().strip()  # Remove newline

    def _set_started(self):
        """Set start time of activity"""
        self.activity_started = self._get_formated_time()

    def _set_ended(self):
        """Set end time of activity"""
        self.activity_ended = self._get_formated_time()

    def _get_formated_time(self):
        """Set timestamp in format YYYYMMDDHHMMZ"""
        return datetime.utcnow().isoformat() + "Z"

    def _set_env(self):
        """Catch and set CONVERT2RHEL_ environment variables"""
        env_list = os.environ
        env_c2r = {}

        # filter just environment variables for C2R
        for env in env_list:
            if re.match(r"^CONVERT2RHEL_", env):
                env_c2r[env] = env_list[env]

        self.env = env_c2r

    def _set_target_os(self):
        self.target_os = systeminfo.SystemInfo._get_system_release_file_content().strip()  # Remove newline

    def _set_success_fail(self):
        self.success = False

    def _set_success_ok(self):
        self.success = True

    def _generate_json(self):
        data = {
            "version": self.version,
            "activity": self.activity,
            "packages": [{"nevra": self.nevra, "signature": self.signature}],
            "executed": self.executed,
            "success": self.success,
            "activity_started": self.activity_started,
            "activity_ended": self.activity_ended,
            "source_os": self.source_os,
            "target_os": self.target_os,
            "env": self.env,
            "run_id": self.run_id,
        }

        write_obj_to_array_json(path=FILE, new_object=data, key="activities")


def sanitize_cli_options(all_cli_options, options_to_sanitize):
    """Change value of CLI options to asterisks to hide sensitive information.

    Return back all options, but sanitized.
    """

    def sanitized_iterator():
        elems = zip_longest(all_cli_options, all_cli_options[1:], fillvalue=None)

        for (c, n) in elems:
            # we need to handle 2 possible cases how arguments are specified
            #  ['--argument=value']
            #  ['--argument', 'value']
            if "=" in c:
                pos = c.index("=")

                if c[:pos] in options_to_sanitize:
                    yield "{}={}".format(c[:pos], ((len(c) - pos - 1) * "*"))
                elif " " in c[pos:]:
                    # if value contains a space we need to add quotes
                    yield '{}="{}"'.format(c[:pos], c[pos + 1 :])
            else:
                if c in options_to_sanitize:
                    yield c
                    if n is not None:
                        yield len(n) * "*"
                    # we've already processed n, so we advance the iterator
                    next(elems, None)
                else:
                    if " " in c:
                        # if value contains a space we need to add quotes
                        yield '"{}"'.format(c)
                    else:
                        yield c

    return " ".join(sanitized_iterator())


def write_obj_to_array_json(path, new_object, key):
    """Write new object to array defined by key in JSON file.

    If the file doesn't exist, create new one and create key for inserting.
    If the file is corrupted, append complete object (with key) as if it was new file and the
    original content of file stays there.
    """
    if not (os.path.exists(path)):
        with open(path, "a") as file:
            file_content = {key: []}
            json.dump(file_content, file, indent=4)

    with open(path, "r+") as file:
        try:
            file_content = json.load(file)  # load data
            # valid json: update the JSON structure and rewrite the file
            file.seek(0)
        # The file contains something that isn't json.
        # Create activities and append to the file, JSON won't be valid, but the content of the file stays there
        # for administrators, etc.
        except ValueError:  # we cannot use json.decoder.JSONDecodeError due python 2.7 compatibility
            file_content = {key: []}

        try:
            file_content[key].append(new_object)  # append new_object to activities
        # valid json, but no 'activities' key there
        except KeyError:
            # create new 'activities' key which contains new_object
            file_content[key] = [new_object]
            # valid json: update the JSON structure and rewrite the file
            file.seek(0)

        # write the json to the file
        json.dump(file_content, file, indent=4)

    # the file can be changed just by root
    os.chmod(path, 0o600)


# Code to be executed upon module import
breadcrumbs = Breadcrumbs()  # pylint: disable=C0103
