# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError

import logging
from subprocess import call
import os
from os.path import isfile, join, exists
from ast import literal_eval
from shutil import copytree, rmtree
from base64 import b64decode
import zipfile, tarfile


_logger = logging.getLogger(__name__)

def clear_folder(folder_path):
    if exists(folder_path):
        if isfile(folder_path):
            os.remove(folder_path)
        else:
            rmtree(folder_path)

class GithubSource(models.Model):
    _name = "module_install.github_source"

    token = fields.Char()
    repository_owner = fields.Char()
    repository_name = fields.Char()
    branch = fields.Char(default="master")
    # TO DO: handle specific git tag or repo subdirectory
    tag = fields.Char(default="latest")
    subdir = fields.Char()

    def _clone_repository(self):
        # TO DO: raise a warning popup in case credentials are missing or invalid
        repo_url = "github.com/{0}/{1}.git".format(self.repository_owner, self.repository_name)
        folder_id = "{0}_{1}_{2}_{3}" \
            .format(self.repository_owner, self.repository_name, self.branch, self.tag)
        temp_folder = "/tmp/" + folder_id
        # If destination folder already exists delete it and clone again repository
        clear_folder(temp_folder)
        cmd = "git clone https://{0}@{1} -b {2} {3}" \
            .format(self.token, repo_url, self.branch, temp_folder)
        if call(cmd, shell=True) == 0:
            _logger.info(self.repository_name + " has been successfully cloned")
            return folder_id
        return ""


class ZipSource(models.Model):
    _name = "module_install.zip_source"

    zip_file = fields.Binary()
    zip_filename = fields.Char()

    def _unzip_file(self):
        # TO DO: raise a warning if file is not set or invalid
        if self.zip_file:
            temp_zip = "/tmp/" + self.zip_filename
            clear_folder(temp_zip)
            with open(temp_zip, 'wb') as f:
                f.write(b64decode(self.zip_file))
            temp_folder = temp_zip.replace('.', '_')
            clear_folder(temp_folder)
            if zipfile.is_zipfile(temp_zip):
                _logger.warning("Archive is a zip.")
                zip_ref = zipfile.ZipFile(temp_zip, 'r')
                zip_ref.extractall(temp_folder)
            elif tarfile.is_tarfile(temp_zip):
                _logger.warning("Archive is a tar.")
                tar_ref = tarfile.open(temp_zip)
                tar_ref.extractall(temp_folder)
            else:
                _logger.warning("Unrecognized compression file format.")
            return temp_folder
        return ""

"""
class SFTPSource(models.Model):
    _name = "module_install.sftp_source"

    username = fields.Char()
    password = fields.Char()
    url = fields.Char()
    path = fields.Char()

    def _get_directory(self):
        # TO DO: handle SFTP connexion and fetch modules
        return ""
"""

class Source(models.Model):
    _name = "module_install.source"
    _inherit = ["module_install.github_source", "module_install.zip_source"]

    source_name = fields.Char(required=True)
    source_type = fields.Selection(selection=[
        ('G', "Github"),
        #('S', "SFTP"),
        ('Z', "Zip"),
    ], string="Source type", default="G", required=True)
    source_install_folder = fields.Char(required=True)
    module_ids = fields.One2many('module_install.wizard', 'source', string="Source modules")


    @api.multi
    def get_source(self):
        root_path = "/tmp"
        folder_id = ""
        if not self._check_fields():
            pass
        elif self.source_type == 'G':
            folder_id = self._clone_repository()
        elif self.source_type == 'Z':
            folder_id = self._unzip_file()
        #elif self.source_type == 'S':
        #    folder_id = self._get_directory()
        if folder_id:
            self._find_module("/tmp", folder_id, True)
        #kanban_id = self.env.ref('module_install_wizard_view').id
        return

    def _check_fields(self):
        if self.source_type == 'G':
            github_fields = ['token', 'repository_owner', 'repository_name', 'branch']
            missing_fields = [f for f in github_fields if not getattr(self, f)]
            if len(missing_fields) > 0:
                msg = "Missing github fields ({}) to clone modules." \
                    .format(", ".join(missing_fields))
                raise UserError(msg)
                return False
        elif self.source_type == 'Z':
            if not self.zip_file:
                raise UserError("Zip file not set to extract modules.")
                return False
        return True

    def _find_module(self, root_path, folder_id, rec=False):
        path = join(root_path, folder_id)
        if not isfile(path):
            module_model = self.env["module_install.wizard"]
            """
            old_modules = module_model.search(['source.id', '=', self.id])
            for m in old_modules:
                msg = "Clearing module {0} for source {1}".format(m, self.source_name)
                _logger.warning(msg)
                m.unlink()
            """
            for f in os.listdir(path):
                filepath = join(path, f)
                if f == "__manifest__.py":
                    datafile = open(filepath, 'r').read()
                    data = literal_eval(datafile)
                    values = {
                        'source': self.id,
                        'module_name': folder_id,
                        'folder_path': path
                    }
                    records = module_model.search([
                        ('folder_path', '=', path),
                    ])
                    _logger.warning(str(len(records)) + " modules found")
                    if len(records) == 0:
                        module_model.create(values)
                    else:
                        records.ensure_one()
                        records.write(values)
                    _logger.info("Module {} found".format(data["name"]))
                if rec:
                    self._find_module(path, f)

    @api.multi
    def write(self, vals):
        _logger.warning(vals)
        if 'source_type' in vals and vals['source_type'] != self.source_type:
            raise UserError("Cannot change source type after source creation")
        else:
            return super(Source, self).write(vals)


class WizardModule(models.TransientModel):
    _name = "module_install.wizard"

    source = fields.Many2one("module_install.source", required=True, ondelete='cascade')
    module_name = fields.Char(string="module")
    folder_path = fields.Char()

    @api.multi
    def install_module(self):
        # Checks if module tmp folder exists, regenerate its source otherwise
        if not self.folder_path or not exists(self.folder_path) \
            or isfile(self.folder_path) or not isfile(self.folder_path + "/__manifest__.py"):
            self.source.get_source()
        try:
            dest = join(self.source.source_install_folder, self.module_name)
            _logger.info("Dest folder: " + dest)
            clear_folder(dest)
            copytree(self.folder_path, dest)
            msg = "Module {0} succesfulled copied to {1}".format(self.module_name, dest)
            raise UserWarning(msg)
        except Exception as e:
            _logger.exception(e)
            raise UserError(str(e))
