from datetime import datetime
from requests.auth import HTTPBasicAuth
import argparse
import json
import pytz
import re
import requests

parser = argparse.ArgumentParser()
parser.add_argument("--azure_pat", type=str, required=True, help="Azure pat")
parser.add_argument(
    "--azure_organisation", type=str, required=True, help="Azure organisation"
)
parser.add_argument("--build_id", type=int, required=True, help="Build id")
parser.add_argument("--done_status_id", type=int, required=True, help="Done status id")
parser.add_argument("--issue_regex", type=str, required=True, help="Issue regex")
parser.add_argument("--jira_token", type=str, required=True, help="Jira token")
parser.add_argument("--jira_username", type=str, required=True, help="Jira username")
parser.add_argument(
    "--jira_organisation", type=str, required=True, help="Jira organisation"
)
parser.add_argument("--pipeline_id", type=int, required=True, help="Pipeline id")
parser.add_argument("--project_name", type=str, required=True, help="Project name")
args = parser.parse_args()
print(f"The build id is: {args.build_id}")

jira_url = f"https://{args.jira_organisation}.atlassian.net/rest/api/3"
jira_username = args.jira_username
jira_token = args.jira_token
jira_credentials = HTTPBasicAuth(jira_username, jira_token)
done_status_id = args.done_status_id
done_status_text = "Done"
default_headers = {"Content-Type": "application/json"}


def label_jira_issue_with_release_date(jira_issue):
    issue_key = jira_issue["key"]
    sydney_timezone = pytz.timezone("Australia/Sydney")
    current_date = datetime.now(sydney_timezone)
    formatted_date = current_date.strftime("%Y%m%d")
    if formatted_date in jira_issue["fields"]["labels"]:
        print(f"Issue {issue_key} is already labelled")
        return

    edit_issue_url = f"{jira_url}/issue/{issue_key}"
    payload = {"update": {"labels": [{"add": formatted_date}]}}

    response = requests.put(
        edit_issue_url,
        data=json.dumps(payload),
        headers=default_headers,
        auth=jira_credentials,
    )

    if response.status_code == 204:
        print(f"Label '{formatted_date}' added to issue {issue_key} successfully.")
    else:
        print(f"Failed to add label. Status code: {response.status_code}")
        print(response.text)


# todo: combine with jira issue edit endpoint
# have to make another api call as the edit endpoint does not support transition yet
def transition_jira_issue_to_done(jira_issue):
    issue_key = jira_issue["key"]
    if jira_issue["fields"]["status"]["name"] == done_status_text:
        print(f"Issue {issue_key} is already in 'Done' status.")
        return

    transition_issue_url = f"{jira_url}/issue/{issue_key}/transitions"
    transition_data = {"transition": {"id": done_status_id}}

    response = requests.post(
        transition_issue_url,
        data=json.dumps(transition_data),
        headers=default_headers,
        auth=jira_credentials,
    )

    if response.status_code == 204:
        print(f"Issue {issue_key} transitioned to 'Done' status successfully.")
    else:
        print(
            f"Failed to transition issue to 'Done' status. Status code: {response.status_code}"
        )
        print(response.text)


def update_jira_issue(issue_key):
    get_issue_url = f"{jira_url}/issue/{issue_key}"
    response = requests.get(
        get_issue_url, headers=default_headers, auth=jira_credentials
    )

    if response.status_code == 200:
        jira_issue = response.json()
        label_jira_issue_with_release_date(jira_issue)
        transition_jira_issue_to_done(jira_issue)
    else:
        print(f"Failed to get issue. Status code: {response.status_code}")
        print(response.text)


def get_jira_issues(builds):
    pattern = rf"{args.issue_regex}"
    jira_issues = []
    for build in builds:
        text = build["triggerInfo"]["ci.message"]
        match = re.search(pattern, text)
        if match:
            jira_issues.append(match.group())
    return jira_issues


def label_jira_issues(builds):
    jira_issues = get_jira_issues(builds)
    if len(jira_issues) == 0:
        print("No jira issues found in the commit messages")
        return

    for jira_issue in jira_issues:
        update_jira_issue(jira_issue)


def find_index_by_property(list, condition):
    return next((index for index, item in enumerate(list) if condition(item)), -1)


azure_pat = args.azure_pat
organisation_url = f"https://dev.azure.com/{args.azure_organisation}"
project_name = args.project_name
api_version = "7.2-preview.7"

pipeline_id = args.pipeline_id
# the build that is being released
release_build_id = args.build_id

# Get builds for a specific pipeline
builds_url = f"{organisation_url}/{project_name}/_apis/build/builds?definitions={pipeline_id}&queryOrder=queueTimeDescending&api-version={api_version}"
builds_response = requests.get(builds_url, auth=HTTPBasicAuth("", azure_pat))

if builds_response.status_code == 200:
    builds_data = builds_response.json()
    builds = builds_data["value"]
    release_build_index = find_index_by_property(
        builds, lambda build: build["id"] == release_build_id
    )
    last_release_index = find_index_by_property(
        builds,
        lambda build: build["status"] == "completed" and build["result"] != "failed",
    )
    last_build = builds[last_release_index]
    print(f"Last build released, Id: {last_build['id']}")
    if last_release_index > release_build_index:
        print("Found unreleased builds")
        builds_not_released = builds[release_build_index:last_release_index]
        label_jira_issues(builds_not_released)
    else:
        print("Old build is being released, thus no labelling is required")
else:
    print(f"Failed to get builds. Status code: {builds_response.status_code}")
