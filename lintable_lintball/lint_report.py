"""LintReport type for use in linting."""

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

from typing import NamedTuple, Dict, List

from lintable_lintball.lint_error import LintError

# The keys in the errors dictionary are the file names of the files linted
LintReport = NamedTuple('LintReport', [('errors', Dict[str, List[LintError]])])


def create_from_db_query(rows)-> LintReport:
    errors = {}

    for row in rows:
        errors.setdefault(row.file_name, []).append(LintError(column=row.column_number,
                                                              line_number=row.line_number,
                                                              msg=row.error_message))

    return LintReport(errors=errors)
