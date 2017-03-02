# -*- coding: utf-8 -*-

from odoo import models, fields, api

import logging
from subprocess import call
import os
from os.path import isfile, join, exists
from ast import literal_eval
from shutil import copytree, rmtree


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

    def _clone_github_repository(self):
        # TO DO: raise a waring popup in case credentials are missing or invalid
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


class Source(models.Model):
    _name = "module_install.source"
    _inherit = ["module_install.github_source",]

    source_type = fields.Selection(selection=[
        ('G', "Github"),
        ('S', "SFTP"),
        ('Z', "Zip"),
    ], string="Source type", default="G")

    @api.multi
    def get_source(self):
        root_path = "/tmp"
        folder_id = ""
        if self.source_type == 'G':
            folder_id = self._clone_github_repository()
        elif self.source_id == 'Z':
            pass
        elif self.source_id == 'S':
            pass
        if folder_id:
            self._check_module("/tmp", folder_id, True)
        return {
            'type': 'ir.actions.act_window',
            'name': "Source modules",
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': 'module_install.wizard',
        }

    def _check_module(self, root_path, folder_id, rec=False):
        path = join(root_path, folder_id)
        if not isfile(path):
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
                    records = self.env["module_install.wizard"].search([
                        ('folder_path', '=', path),
                    ])
                    _logger.warning(str(len(records)) + " modules found")
                    if len(records) == 0:
                        self.env["module_install.wizard"].create(values)
                    else:
                        records.ensure_one()
                        records.write(values)
                    print "Module {} found".format(data["name"])
                    #return True
                if rec:
                    self._check_module(path, f)
        #return False


class WizardModule(models.TransientModel):
    _name = "module_install.wizard"

    source = fields.Many2one("module_install.source", required=True, ondelete='cascade')
    module_name = fields.Char(string="module")
    folder_path = fields.Char()

    @api.multi
    def install_module(self):
        # Check if module tmp folder exists, regenerate its source otherwise
        if not self.folder_path or not exists(self.folder_path) \
            or isfile(self.folder_path) or not isfile(self.folder_path + "/__manifest__.py"):
            self.source.get_source()
        dest = join("/opt/module_install", self.module_name)
        clear_folder(dest)
        copytree(self.folder_path, dest)



