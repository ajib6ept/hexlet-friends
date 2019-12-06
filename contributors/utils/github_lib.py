from collections import Counter
from urllib.parse import parse_qs, urlparse

import requests
from django.conf import settings
from django.db import models

GITHUB_API_URL = 'https://api.github.com'


class GitHubError(Exception):
    """GitHub error."""


class NoContent(GitHubError):
    """HTTP 204 Response."""


class NoContributorsError(GitHubError):
    """A repository has no contributors."""


class ContributorNotFoundError(GitHubError):
    """A particular contributor was not found."""


def get_headers():
    """Return headers to use in a request."""
    return {'Authorization': f'token {settings.GITHUB_AUTH_TOKEN}'}


def get_one_item_at_a_time(url, additional_params=None, session=None):
    """Return data from all pages (one instance at a time)."""
    query_params = {'page': 1}
    query_params.update(additional_params or {})
    req = session or requests
    response = req.get(url, headers=get_headers(), params=query_params)
    response.raise_for_status()
    yield from response.json()

    pages_count = get_pages_count(response.links)
    while query_params['page'] < pages_count:
        query_params['page'] += 1
        response = req.get(
            url, headers=get_headers(), params=query_params,
        )
        response.raise_for_status()
        yield from response.json()


def get_whole_response_as_json(url, session=None):
    """Return data as given by GitHub (a batch)."""
    req = session or requests
    response = req.get(url, headers=get_headers())
    response.raise_for_status()
    if response.status_code == requests.codes.no_content:
        raise NoContent("204 No Content")
    return response.json()


def get_org_data(org, session=None):
    """Return an organization's data."""
    url = f'{GITHUB_API_URL}/orgs/{org}'
    return get_whole_response_as_json(url, session)


def get_repo_data(repo, session=None):
    """Return a repository's data."""
    url = f'{GITHUB_API_URL}/repos/{repo}'
    return get_whole_response_as_json(url, session)


def get_user_data(user, session=None):
    """Return a user's data."""
    url = f'{GITHUB_API_URL}/users/{user}'
    return get_whole_response_as_json(url, session)


def get_user_name(url, session=None):
    """Return a user's name."""
    return get_whole_response_as_json(url, session)['name']


def get_org_repos(org, session=None):
    """Return repositories of an organization."""
    url = f'{GITHUB_API_URL}/orgs/{org}/repos'
    return get_one_item_at_a_time(url, {'type': 'sources'}, session)


def get_repo_contributors(owner, repo, session=None):
    """Return contributors for a repository."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/stats/contributors'
    contributors = []
    for contributor in get_whole_response_as_json(url, session):
        contributor['login'] = contributor['author']['login']
        contributors.append(contributor)
    return contributors


def get_repo_commits(owner, repo, session=None):
    """Return all commits for a repository."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/commits'
    return get_one_item_at_a_time(url, session)


def get_repo_prs(owner, repo, session=None):
    """Return all pull requests for a repository."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/pulls'
    query_params = {'state': 'all'}
    return get_one_item_at_a_time(url, query_params, session)


def get_repo_issues(owner, repo, session=None):
    """
    Return all issues for a repository.

    Every pull request is an issue, but not every issue is a pull request.
    Identify pull requests by the `pull_request` key.
    [issue for issue in issues if 'pull_request' not in issue]
    """
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/issues'
    query_params = {'state': 'all'}
    return get_one_item_at_a_time(url, query_params, session)


def get_comments_for_issue(owner, repo, issue_number, session=None):
    """Return all comments for an issue."""
    url = (
        f'{GITHUB_API_URL}/repos/{owner}/{repo}/issues/{issue_number}/comments'
    )
    return get_one_item_at_a_time(url, session=session)


def get_repo_comments(owner, repo, session=None):
    """Return all comments for a repository."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/issues/comments'
    return get_one_item_at_a_time(url, session=session)


def get_review_comments_for_pr(owner, repo, pr_number, session=None):
    """Return all review comments for a pull request."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}/comments'
    return get_one_item_at_a_time(url, session=session)


def get_repo_review_comments(owner, repo, session=None):
    """Return all review comments for a repository."""
    url = f'{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/comments'
    return get_one_item_at_a_time(url, session=session)


def get_total_contributions_per_user(contributions, author_field_name):
    """Return total numbers of contributions of a specific type per user."""
    users_contributions_totals = {}
    for contribution in contributions:
        author = contribution.get(author_field_name)
        if not author:  # Deleted user
            continue
        login = author.get('login')
        users_contributions_totals[login] = (
            users_contributions_totals.get(login, 0) + 1
        )
    return users_contributions_totals


def get_total_changes_per_user(contributors, change_type):
    """Return total numbers of changes of `type` made by each user."""
    total_changes_per_user = {}
    for contribution in contributors:
        login = contribution['login']
        total_changes_per_user[login] = sum(
            week[change_type] for week in contribution['weeks']
        )
    return total_changes_per_user


def get_total_prs_per_user(prs):
    """Return total numbers of pull requests per user."""
    return get_total_contributions_per_user(prs, 'user')


def get_total_commits_per_user(commits):
    """Return total numbers of commits per user."""
    return get_total_contributions_per_user(commits, 'author')


def get_total_commits_per_user_excluding_merges(owner, repo):
    """Return total numbers of commits per user excluding merge commits."""
    contributors = get_repo_contributors(owner, repo)
    return {
        contributor['login']: contributor['total']
        for contributor in contributors
    }


def get_total_issues_per_user(issues):
    """Return total numbers of issues per user."""
    return get_total_contributions_per_user(issues, 'user')


def get_total_comments_per_user(comments):
    """Return total numbers of comments per user."""
    return get_total_contributions_per_user(comments, 'user')


def get_total_additions_per_user(contributors):
    """Return total numbers of additions per user."""
    return get_total_changes_per_user(contributors, 'a')


def get_total_deletions_per_user(contributors):
    """Return total numbers of deletions per user."""
    return get_total_changes_per_user(contributors, 'd')


def get_pages_count(link_headers):
    """Return a number of pages for a resource."""
    if 'last' in link_headers:
        return int(
            parse_qs(urlparse(link_headers['last']['url']).query)['page'][0],
        )
    return 1


def merge_dicts(*dicts):
    """Merge several dictionaries into one."""
    counter = Counter()
    for dict_ in dicts:
        counter.update(dict_)
    return counter


def get_commit_stats_for_contributor(
    repo_full_name, contributor_id, session=None,
):
    """Return numbers of commits, additions, deletions of a contributor."""
    url = f'{GITHUB_API_URL}/repos/{repo_full_name}/stats/contributors'
    req = session or requests
    response = req.get(url, headers=get_headers())
    response.raise_for_status()
    if response.status_code == requests.codes.no_content:
        raise NoContributorsError(
            "Nobody has contributed to this repository yet",
        )

    try:
        contributor_stats = [
            stats for stats in response.json()
            if stats['author']['id'] == contributor_id
        ][0]
    except IndexError:
        raise ContributorNotFoundError(
            "No such contributor in this repository",
        )

    totals = merge_dicts(*contributor_stats['weeks'])

    return totals['c'], totals['a'], totals['d']


def get_or_create_record(obj, github_resp, additional_fields=None):   # noqa WPS110
    """
    Get or create a database record based on GitHub JSON object.

    Args:
        obj -- model or instance of a model
        github_resp -- GitHub data as a JSON object decoded to dict
        additional_fields -- fields to override
    """
    model_fields = {
        'Organization': {'name': github_resp.get('login')},
        'Repository': {'full_name': github_resp.get('full_name')},
        'Contributor': {
            'login': github_resp.get('login'),
            'avatar_url': github_resp.get('avatar_url'),
        },
    }
    defaults = {
        'name': github_resp.get('name'),
        'html_url': github_resp.get('html_url'),
    }
    if isinstance(obj, models.Model):
        class_name = obj.repository_set.model.__name__
        manager = obj.repository_set
    else:
        class_name = obj.__name__
        manager = obj.objects

    defaults.update(model_fields[class_name])
    defaults.update(additional_fields or {})
    return manager.get_or_create(
        id=github_resp['id'],
        defaults=defaults,
    )
