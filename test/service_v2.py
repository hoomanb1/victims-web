# This file is part of victims-web.
#
# Copyright (C) 2013 The Victims Project
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Service version 2 testing.
"""

import json
from StringIO import StringIO
from base64 import b64encode
from datetime import datetime
from hashlib import md5
from shutil import rmtree

from os import listdir
from os.path import isdir

from test import UserTestCase
from victims.web.config import DEFAULT_GROUP, UPLOAD_FOLDER, VICTIMS_API_HEADER
from victims.web.handlers.security import generate_signature
from victims.web.models import Removal, Submission


class TestServiceV2(UserTestCase):
    """
    Tests for version 2 of the web service.
    """

    username = 'v2tester'
    points = ['update', 'remove']

    def tearDown(self):
        if isdir(UPLOAD_FOLDER):
            rmtree(UPLOAD_FOLDER)
            for submission in Submission.objects(submitter=self.username):
                submission.delete()

        UserTestCase.tearDown(self)

    def test_uri_endpoints(self):
        """
        Verify the basic endpoints respond as they should.
        """
        for kind in self.points:
            resp = self.app.get('/service/v2/%s/1970-01-01T00:00:00/' % kind)
            assert resp.status_code == 200
            assert resp.content_type == 'application/json'

        # V1 returns empty list when nothing is available
        for kind in self.points:
            resp = self.app.get('/service/v2/%s/4000-01-01T00:00:00/' % kind)
            assert resp.status_code == 200
            assert resp.content_type == 'application/json'

        # Anything that is not a valid API call should return 404
        for kind in self.points:
            for badtype in [0, 'NotAnInt', 10.436, 0x80, u'bleh']:
                resp = self.app.get('/service/v2/%s/%s/' % (kind, badtype))
                assert resp.status_code == 404
                assert resp.content_type == 'application/json'

    def test_update_defaults(self):
        """
        Verify that update defaults works as expected.
        """
        FULL_ROUTE = '/service/v2/update/java/1970-01-01T00:00:00/'
        ROUTES_WITH_DEFAULTS = [
            '/service/v2/update/java/',
            '/service/v2/update/1970-01-01T00:00:00/'
        ]

        expected = self.app.get(FULL_ROUTE, follow_redirects=True)

        for route in ROUTES_WITH_DEFAULTS:
            resp = self.app.get(route, follow_redirects=True)
            assert resp.status_code == 200
            assert resp.content_type == 'application/json'
            assert resp.data == expected.data

    def verify_data_structure(self, result, expected, two_way=False):
        assert len(result) > 0
        for item in result:
            assert 'fields' in item.keys()
            for key, testtype in expected.items():
                assert isinstance(item['fields'][key], testtype)
            if two_way:
                for key in item['fields']:
                    assert key in expected

    def test_updates(self):
        """
        Ensures the response structure is correct for a GET request.
        """
        expected = {
            'date': basestring,
            'name': basestring,
            'version': basestring,
            'format': basestring,
            'hashes': dict,
            'vendor': basestring,
            'cves': list,
            'status': basestring,
            'meta': list,
            'submitter': basestring,
            'submittedon': basestring,
        }

        params = 'fields=%s' % (','.join(expected.keys()))
        resp = self.app.get(
            '/service/v2/update/1970-01-01T00:00:00/?%s' % (params)
        )
        result = json.loads(resp.data)
        self.verify_data_structure(result, expected)

    def test_filtered_updates(self):
        """
        Ensures the response structure is correct for a POST request.
        """
        resp = self.app.get(
            '/service/v2/update/1970-01-01T00:00:00?fields=name,hashes',
            follow_redirects=True
        )
        result = json.loads(resp.data)

        expected = {
            'name': basestring,
            'hashes': dict
        }
        self.verify_data_structure(result, expected, True)

    def test_cves_valid(self):
        """
        Ensure valid cve (hash) search works
        """
        # Test for valid sha512
        sha512 = "a0a86214ea153fb07ff35ceec0848dd1703eae22de036a825efc8" + \
            "394e50f65e3044832f3b49cf7e45a39edc470bdf738abc36a3a78c" + \
            "a7df3a6e73c14eaef94a8"
        resp = self.app.get('/service/v2/cves/%s/%s/' % ('sha512', sha512))
        result = json.loads(resp.data)
        assert isinstance(result, list)
        assert 'CVE-1969-0001' in result[0]['fields']["cves"]

    def test_cves_invalid(self):
        """
        Ensure invalid cve (hash) search is caught
        """
        # Test for invalid algorithm
        resp = self.app.get('/service/v2/cves/%s/%s/' % ('invalid', 'invalid'))
        result = json.loads(resp.data)
        assert resp.status_code == 400
        assert isinstance(result, list)
        assert result[0]['error'].find('Invalid alogrithm') >= 0

        # Test for invalid argument length
        resp = self.app.get('/service/v2/cves/%s/%s/' % ('sha1', '0'))
        result = json.loads(resp.data)
        assert resp.status_code == 400
        assert isinstance(result, list)
        assert result[0]['error'].find('Invalid checksum length for sha1') >= 0

    def test_cves_coordinates_invalid(self):
        """
        Ensure invalid cve (coordinates) is caught
        """
        base = '/service/v2/cves/java/'
        resp = self.app.get(base)
        assert resp.status_code == 400

    def test_cves_coordinates(self):
        """
        Ensure valid cve (coordinates) search works
        """
        base = '/service/v2/cves/java/'
        uri1 = '%s?groupId=fake' % (base)
        uri2 = '%s&version=1.0' % (uri1)
        for uri in [uri1, uri2]:
            resp = self.app.get(uri)
            assert resp.status_code == 200
            result = json.loads(resp.data)
            assert isinstance(result, list)
            assert 'CVE-1969-0001' in result[0]['fields']["cves"]

    def test_status(self):
        """
        Verifies the status data is correct.
        """
        resp = self.app.get('/service/v2/status.json')
        assert resp.content_type == 'application/json'

        result = json.loads(resp.data)
        assert result['version'] == '2'
        assert result['recommended'] is True
        assert result['eol'] is None
        assert result['supported'] is True
        assert result['endpoint'] == '/service/v2/'

    def test_removals(self):
        test_hash = 'ABC123'
        removal = Removal()
        removal.hash = test_hash
        removal.group = DEFAULT_GROUP
        removal.validate()
        removal.save()
        resp = self.app.get(
            '/service/v2/remove/1970-01-01T00:00:00', follow_redirects=True)
        assert resp.status_code == 200
        assert resp.content_type == 'application/json'
        assert test_hash in resp.data

    def json_submit(self, path, data, content_type, md5sums, status_code,
                    apikey, secret):
        date = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')
        headers = [('Date', date)]
        if apikey is not None and secret is not None:
            signature = generate_signature(apikey, 'PUT', path, date, md5sums)
            headers.append((VICTIMS_API_HEADER, '%s:%s' % (apikey, signature)))
        resp = self.app.put(
            path, headers=headers,
            data=data,
            follow_redirects=True,
            content_type=content_type
        )
        assert resp.status_code == status_code
        assert resp.content_type == 'application/json'

    def json_submit_hash(self, group, status_code, apikey=None, secret=None):
        testhash = dict(combined="AAAA")
        testhashes = dict(sha512=testhash)
        testdata = dict(name="", hashes=testhashes, cves=['CVE-2013-0000'])
        testdata = json.dumps(testdata)
        path = '/service/v2/submit/hash/%s/' % (group)
        md5sums = [md5(testdata).hexdigest()]
        self.json_submit(
            path, testdata, 'application/json',
            md5sums, status_code, apikey, secret
        )

    def make_submission_archive(self):
        testfilename = 'testfile.jar'
        content = 'test content'
        md5sum = md5(content).hexdigest()
        data = {'archive': (StringIO(content), testfilename)}
        return (testfilename, md5sum, data)

    def is_uploaded(self, filename, cleanup=True):
        uploaded = False
        if isdir(UPLOAD_FOLDER):
            files = [
                f for f in listdir(UPLOAD_FOLDER) if f.endswith(filename)
            ]
            uploaded = len(files) > 0

        if isdir(UPLOAD_FOLDER):
            rmtree(UPLOAD_FOLDER)

        return uploaded

    def basicauth_submission(self, username, password, code=201):
        (testfilename, _, data) = self.make_submission_archive()
        path = '/service/v2/submit/archive/java/?cves=CVE-000-000'

        headers = {
            'Authorization':
            'Basic ' + b64encode('%s:%s' % (username, password))
        }
        resp = self.app.put(
            path=path,
            headers=headers,
            data=data,
            follow_redirects=True,
        )

        uploaded = self.is_uploaded(testfilename)

        assert resp.status_code == code

        if code == 201:
            assert uploaded
        else:
            assert not uploaded

    def test_valid_basicauth(self):
        """
        Verify that a valid basicauth submission works
        """
        self.create_user(self.username, self.password)
        self.basicauth_submission(self.username, self.password)

    def test_invalid_basicauth(self):
        """
        Verify that an invalid basiauth submission fails
        """
        self.basicauth_submission(self.username, 'WRONGPASS', 403)

    def json_submit_file(self, group, status_code, argstr=None, apikey=None,
                         secret=None):
        (testfilename, filemd5, data) = self.make_submission_archive()
        md5sums = [filemd5]
        path = '/service/v2/submit/archive/%s/' % (group)
        if argstr:
            path = '%s?%s' % (path, argstr)

        self.json_submit(
            path, data, 'multipart/form-data',
            md5sums, status_code, apikey, secret
        )

        uploaded = self.is_uploaded(testfilename)

        if status_code == 201:
            assert uploaded
        else:
            assert not uploaded

    def test_lastapi(self):
        """
        Verify that last api time is updated
        """
        self.create_user(self.username, self.password)
        self._login(self.username, self.password)
        last = datetime.utcnow()
        self.json_submit_hash(
            'java', 201, self.account.apikey, self.account.secret
        )
        self.account.reload()
        assert last < self.account.lastapi

    def test_java_submission_authenticated(self):
        """
        Verifies that an authenticated user can submit entries via the JSON API
        """
        self.create_user(self.username, self.password)
        self._login(self.username, self.password)
        self.json_submit_hash(
            'java', 201, self.account.apikey, self.account.secret
        )
        self.json_submit_file(
            'java', 400, None, self.account.apikey, self.account.secret
        )
        self.json_submit_file(
            'java', 201, 'cves=CVE-2013-000', self.account.apikey,
            self.account.secret
        )
        self._logout()

    def test_java_submission_anon(self):
        """
        Verfies that an unauthenticated user cannot submit via the JSON API
        """
        self.json_submit_hash('java', 403)
        self.json_submit_file('java', 403)
