"""Supplies the frontend pages."""

# Copyright 2015-2016 Capstone Team G
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import urllib.parse
from typing import Iterable

import github
import requests
from flask import (Flask, request, render_template, redirect, url_for,
                   abort, flash)
from flask_login import (LoginManager, login_user, login_required, logout_user,
                         current_user)
from github import Github

from lintable_db.database import DatabaseHandler
from lintable_db.models import User, database, Repo
from lintable_settings.settings import LINTWEB_SETTINGS
from lintable_lintball import lintball
from lintable_web.WebhookForm import WebhookForm

app = Flask(__name__)  # pylint: disable=invalid-name
app.secret_key = LINTWEB_SETTINGS['SESSIONS_SECRET']


# This hook ensures that a connection is opened to handle any queries
# generated by the request.
@app.before_request
def _db_connect():
    database.connect()


# This hook ensures that the connection is closed when we've finished
# processing the request.
@app.teardown_request
def _db_close(exc):
    if not database.is_closed():
        database.close()


login_manager = LoginManager()
login_manager.login_view = 'github_oauth'
login_manager.init_app(app)

LOGGER = logging.getLogger(__name__)
DEBUG = LINTWEB_SETTINGS['DEBUG']


################################################################################
# Authentication helpers
################################################################################

@login_manager.user_loader
def load_user(identifier: str) -> User:
    """Return a User object based on the given identifier."""

    return DatabaseHandler.get_user(int(identifier))


################################################################################
# Views
################################################################################

@app.route('/')
def index():
    """View the homepage."""

    if DEBUG:
        return render_template('coming_soon.html')

    if not DEBUG:
        return render_template('index.html')


if not DEBUG:
    @app.route('/account')
    @login_required
    def account():
        """View details for an existing user account."""
        LOGGER.error('in account .... current_user.github_id: {}'.format(current_user.github_id))

        return render_template('account.html', current_user=current_user)


    @app.route('/status')
    @app.route('/status/<identifier>')
    @login_required
    def status(identifier=None):
        """Get active jobs for the current user, or status of a job in progress.

        :param identifier: A UUID identifying the job.
        """

        if identifier is None:
            return render_template('status.html')

        LOGGER.error('Retriving job: {}'.format(identifier))
        job = DatabaseHandler.get_job(identifier)
        LOGGER.error('Retrieved job: {}'.format(job.job_id))

        if job is None:
            abort(404)

        if job.repo_owner.github_id != current_user.github_id:
            abort(403)

        LOGGER.error('returning status for job.job_id: {}'.format(job.job_id))
        return render_template('status.html', job=job)


    @app.route('/terms')
    def terms():
        """View the terms of service."""
        # TODO: Possibly pull content from Markdown file
        return render_template('terms.html')


    @app.route('/privacy')
    def privacy():
        """View the privacy policy."""
        # TODO: Possibly pull content from Markdown file
        return render_template('privacy.html')


    @app.route('/security')
    def security():
        """View the security info."""
        # TODO: Possibly pull content from Markdown file
        return render_template('security.html')


    @app.route('/support')
    def support():
        """View the support page."""
        return render_template('support.html')


    @app.route('/payload', methods=['POST'])
    def github_payload():
        """Trigger processing of a JSON payload."""
        payload = request.get_json()
        target_url = url_for('status', _external=True)
        lintball.lint_github.delay(payload=payload, target_url=target_url)
        return 'successy'


    @app.route('/login')
    def login():
        return redirect(url_for('github_oauth'))


    @app.route('/register')
    def github_oauth():
        """Redirect user to github OAuth registeration page."""

        url = LINTWEB_SETTINGS['github']['OAUTH_URL']
        params = {
            'client_id': LINTWEB_SETTINGS['github']['CLIENT_ID'],
            'redirect_uri': LINTWEB_SETTINGS['github']['CALLBACK'],
            'scope': LINTWEB_SETTINGS['github']['SCOPES']
        }

        params_str = urllib.parse.urlencode(params)
        url = '{}?{}'.format(url, params_str)

        return redirect(url, code=302)


    @app.route('/list/repositories', methods=('GET', 'POST'))
    @login_required
    def list_repos():
        """List repositories for a given owner."""

        github_id = current_user.github_id
        LOGGER.error('current_user: {github_id}'.format(github_id=github_id))

        owner = DatabaseHandler.get_user(current_user.github_id)
        oauth_key = owner.get_oauth_token()
        client_id = LINTWEB_SETTINGS['github']['CLIENT_ID']

        client_secret = LINTWEB_SETTINGS['github']['CLIENT_SECRET']

        github_api = Github(login_or_token=oauth_key,
                            client_id=client_id,
                            client_secret=client_secret)

        if request.method == 'GET':
            form = WebhookForm()
        else:
            form = WebhookForm(request.form)

        repos = {}

        try:
            has_webhooks = Repo.select(Repo.id).where(Repo.owner == github_id).dicts()
        except Exception as e:
            has_webhooks = []
            LOGGER.error('failed to get repo from database with exception {e}'.format(e=e))

        LOGGER.error('webhooks: {}'.format(has_webhooks))

        for repo in github_api.get_user().get_repos(type='owner'):
            full_name = repo.full_name
            has_webhook = dict(id=repo.id) in has_webhooks
            repos[full_name] = has_webhook

        for full_name, has_webhook in repos.items():
            LOGGER.error('full_name: {full_name}\t\twebhook?: {webhook}'.format(full_name=full_name,
                                                                                webhook=has_webhook))

        form.webhooks.choices = [(full_name, full_name) for full_name, has_webhook in repos.items()]

        if request.method == 'POST' and form.validate():
            LOGGER.error('checking for updates')
            LOGGER.error('webhooks: {}'.format(repr(form.webhooks)))
            LOGGER.error('webhook data: {}'.format(repr(form.webhooks.data)))
            change_webhooks = form.webhooks.data if form.webhooks and form.webhooks.data else []
            add_webhooks = set()
            remove_webhooks = set()

            for full_name, has_webhook in repos.items():
                if full_name in change_webhooks and not has_webhook:
                    add_webhooks.add(full_name)
                if full_name not in change_webhooks and has_webhook:
                    remove_webhooks.add(full_name)

            LOGGER.error('webhooks to add: {}'.format(add_webhooks))
            LOGGER.error('webhooks to remove: {}'.format(remove_webhooks))
            add_webhook(github_api, owner, add_webhooks)
            remove_webhook(github_api, remove_webhooks)
        else:
            LOGGER.error('presenting form')


        try:
            result = render_template('list_repos.html', current_user=current_user, form=form)
        except Exception as e:
            result = ''
            LOGGER.error('failed to render html with {e}'.format(e=e))

        return result

    def add_webhook(github_api: Github, owner: User, full_names: Iterable[str]):

        try:
            name = url_for('index', _external=True)
            config = dict(url=url_for('payload', _external=True),
                          content_type='json',
                          secret='')
            events = ['pull_request']
            active = True
        except Exception as e:
            LOGGER.error('exception while creating data for webhook creation: {}'.format(e))
            return

        for full_name in full_names:
            LOGGER.error('creating webhook for repo {}'.format(full_name))

            github_repo = github_api.get_repo(full_name)
            hook = github_repo.create_hook(name=name, config=config, events=events, active=active)

            LOGGER.error('webhook addition: repo = {}'.format(github_repo))
            LOGGER.error('webhook addition: hook = {}'.format(hook))

            if hook:
                try:
                    repo = Repo.create_or_get(repo_id=github_repo.id, owner_id=owner)
                    repo.save()
                except Exception as e:
                    LOGGER.error('failed to save repo record with exception: {}'.format(e))

        return

    def remove_webhook(github_api: Github, full_names: Iterable[str]):
        payload_url = url_for('payload', _external=True)

        for full_name in full_names:
            LOGGER.error('deleting webhook for repo {}'.format(full_name))

            github_repo = github_api.get_repo(full_name)

            LOGGER.error('webhook deletion: repo = {}'.format(github_repo))

            for hook in github_repo.get_hooks():
                if hook.url == payload_url:
                    LOGGER.error('webhook deletion: hook = {}'.format(hook))
                    hook.delete()

                    try:
                        repo = DatabaseHandler.get_repo(github_repo.id)
                        repo.delete()
                    except Exception as e:
                        LOGGER.error('failed to delete repo record with exception: {}'.format(e))

        return

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('index'))


    @app.route('/callback')
    def github_oauth_response():
        """Receive OAuth code and retrieve token."""

        code = request.args.get('code')
        url = LINTWEB_SETTINGS['github']['OAUTH_URL_POST']

        if code is None:
            return "No github code found"

        # Construct outgoing data and a header
        outgoing = {
            'client_id': LINTWEB_SETTINGS['github']['CLIENT_ID'],
            'client_secret': LINTWEB_SETTINGS['github']['CLIENT_SECRET'],
            'code': code,
            'redirect_url': LINTWEB_SETTINGS['github']['CALLBACK']
        }
        headers = {'Accept': 'application/json'}

        # Post data to github and capture response then parse returned JSON
        github_request = None
        try:
            github_request = requests.post(url, data=outgoing, headers=headers)
        except requests.exceptions.RequestException as ex:
            LOGGER.error('Error posting to github: %s', ex)

        payload = json.loads(github_request.text)
        access_token = payload['access_token']
        scope_given = payload['scope'].split(',')

        # Check if we were given the right permissions
        scope_needed = LINTWEB_SETTINGS['github']['SCOPES'].split(',')
        for perm in scope_needed:
            if perm not in scope_given:
                flash('You did not accept our permissions.')
                return redirect(url_for('index'))

        github_user = Github(access_token).get_user()
        github_user_id = github_user.id
        github_name = github_user.name
        if not github_name:
            github_name = github_user.login

        user = DatabaseHandler.get_user(github_user_id)
        if user is None:
            user = User(github_id=github_user_id, token=access_token,
                        username=github_name)
            user.save()

        login_user(user)
        LOGGER.error('current_user.github_id: {}'.format(current_user.github_id))
        LOGGER.error('user.github_id: {}'.format(user.github_id))

        flash('Logged in successfully.')
        LOGGER.error('request.args.get(\'next\') : {}'.format(request.args.get('next')))
        LOGGER.error('url_for(\'account\'): {}'.format(url_for('account')))
        return redirect(request.args.get('next') or url_for('account'))

################################################################################
# Start the server
################################################################################

if __name__ == '__main__':
    print("running app: ", __name__)
    app.run()
