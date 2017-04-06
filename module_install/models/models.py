# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

import logging
import subprocess
from os import path
import os
from ast import literal_eval
from shutil import copytree, rmtree
from base64 import b64decode
import zipfile, tarfile


_logger = logging.getLogger(__name__)

def clear_folder(folder_path):
    if path.exists(folder_path):
        if path.isfile(folder_path):
            os.remove(folder_path)
        else:
            rmtree(folder_path)

class GithubSource(models.Model):
    _name = "module_install.github_source"

    token = fields.Char(default="")
    repository_owner = fields.Char()
    repository_name = fields.Char()
    branch = fields.Char(default="master")
    # TODO: handle specific git tag or repo subdirectory
    tag = fields.Char(default="latest")
    subdir = fields.Char()

    def _clone_repository(self):
        # TODO: raise a warning popup in case credentials are missing or invalid
        repo_url = "github.com/{0}/{1}.git".format(self.repository_owner, self.repository_name)
        folder_id = "{0}_{1}_{2}_{3}" \
            .format(self.repository_owner, self.repository_name, self.branch, self.tag)
        temp_folder = "/tmp/" + folder_id
        # If destination folder already exists delete it and clone again repository
        clear_folder(temp_folder)
        cmd = "git clone https://{token}@{url} -b {branch} {dest}".format(
            token=self.token,
            url=repo_url,
            branch=self.branch,
            dest=temp_folder
        )
        _logger.info("Running: " + cmd)
        try:
            if subprocess.Popen(cmd.split(" ")).wait() == 0:
                _logger.info(self.repository_name + _(" has been successfully cloned"))
                return folder_id
        except Exception as e:
            _logger.exception(e)
        return ""


class ZipSource(models.Model):
    _name = "module_install.zip_source"

    zip_file = fields.Binary()
    zip_filename = fields.Char()

    def _unzip_file(self):
        # TODO: raise a warning if file is not set or invalid
        if self.zip_file:
            temp_zip = "/tmp/" + self.zip_filename
            clear_folder(temp_zip)
            with open(temp_zip, 'wb') as f:
                f.write(b64decode(self.zip_file))
            temp_folder = temp_zip.replace('.', '_')
            clear_folder(temp_folder)
            if zipfile.is_zipfile(temp_zip):
                _logger.info(_("Archive is a zip file."))
                zip_ref = zipfile.ZipFile(temp_zip, 'r')
                zip_ref.extractall(temp_folder)
            elif tarfile.is_tarfile(temp_zip):
                _logger.warning(_("Archive is a tar file."))
                tar_ref = tarfile.open(temp_zip)
                tar_ref.extractall(temp_folder)
            else:
                _logger.warning(_("Unrecognized compression file format."))
            return temp_folder
        return ""


class Source(models.Model):
    _name = "module_install.source"
    _inherit = ["module_install.github_source", "module_install.zip_source"]

    source_name = fields.Char(required=True)
    source_type = fields.Selection(selection=[
        ('G', "Github"),
        ('Z', "Zip"),
    ], string="Source type", default="G", required=True)
    source_install_folder = fields.Char(default="/mnt/extra-addons", required=True)
    search_depth = fields.Integer(default=0)
    module_ids = fields.One2many('module_install.wizard', 'source', string="Source modules")

    @api.constrains('search_depth')
    def _check_depth(self):
        _MAX_DEPTH = 5
        for record in self:
            if record.search_depth < 0:
                raise ValidationError(_("Search depth must be a positive value."))
            elif record.search_depth > _MAX_DEPTH:
                msg = _("Maximum search depth allowed is {}.").format(_MAX_DEPTH)
                raise ValidationError(msg)

    @api.multi
    def get_source(self):
        for record in self:
            folder_id = ""
            record._check_fields()
            if record.source_type == 'G':
                folder_id = record._clone_repository()
            elif record.source_type == 'Z':
                folder_id = record._unzip_file()
            if folder_id:
                record._find_module(path.join("/tmp", folder_id), self.search_depth)
            else:
                msg = _("No modules found with search level {}".format(record.search_depth))
                _logger.warning(msg)

    def _check_fields(self):
        if self.source_type == 'G':
            github_fields = ['repository_owner', 'repository_name', 'branch']
            missing_fields = [f for f in github_fields if not getattr(self, f)]
            if len(missing_fields) > 0:
                msg = _("Missing github fields ({}) to clone modules.") \
                    .format(", ".join(missing_fields))
                raise UserError(msg)
        elif self.source_type == 'Z':
            if not self.zip_file:
                raise UserError(_("Zip file not set to extract modules."))

    def _find_module(self, module_path, depth=0):
        #path = join(root_path, folder_id)
        if not path.isfile(module_path):
            module_model = self.env["module_install.wizard"]
            """
            old_modules = module_model.search(['source.id', '=', self.id])
            for m in old_modules:
                msg = "Clearing module {0} for source {1}".format(m, self.source_name)
                _logger.warning(msg)
                m.unlink()
            """
            for filename in os.listdir(module_path):
                _logger.debug("Searching modules in {0} - depth: {1} - file: {2}".format(module_path, depth, filename))
                filepath = path.join(module_path, filename)
                if depth > 0:
                    if not path.isfile(filepath):
                        self._find_module(filepath, depth - 1)
                elif filename == "__manifest__.py":
                    datafile = open(filepath, 'r').read()
                    data = literal_eval(datafile)
                    values = {
                        'source': self.id,
                        'name': path.basename(module_path),
                        'description': data['name'],
                        'version': data['version'],
                        'folder_path': module_path
                    }
                    records = module_model.search([
                        ('folder_path', '=', module_path),
                    ])
                    _logger.info(str(len(records)) + _(" modules found"))
                    # TODO: Refresh all source's module list and remove unused ones
                    if len(records) == 0:
                        module_model.create(values)
                    else:
                        records.ensure_one()
                        records.write(values)
                    _logger.info("Module {} found".format(data["name"]))

    @api.multi
    def write(self, vals):
        _logger.warning(vals)
        if 'source_type' in vals and vals['source_type'] != self.source_type:
            _logger.error(_("Cannot change source type after source creation"))
        else:
            return super(Source, self).write(vals)


class WizardModule(models.TransientModel):
    _name = "module_install.wizard"

    source = fields.Many2one("module_install.source", required=True, ondelete='cascade')
    name = fields.Char()
    description = fields.Char()
    version = fields.Char()
    folder_path = fields.Char()

    @api.multi
    def install_module(self):
        # Checks if module tmp folder exists, regenerate its source otherwise
        for record in self:
            if not record.folder_path or not path.exists(record.folder_path) \
                or path.isfile(record.folder_path) \
                or not path.isfile(record.folder_path + "/__manifest__.py"):
                record.source.get_source()
                msg = _("A problem occurred while downloading module {}, reloading source files") \
                    .format(record.name)
                _logger.error(msg)
                #raise UserError(msg)
            dest = path.join(record.source.source_install_folder, record.name)
            # TODO: CLeaner and more specific user error handling
            try:
                clear_folder(dest)
                copytree(record.folder_path, dest)
                msg = _("Module {0} succesfulled copied to {1}").format(record.name, dest)
                _logger.info(msg)
                #raise UserWarning(msg)
            except Exception as e:
                _logger.exception(e)
                #raise UserError(repr(e))
