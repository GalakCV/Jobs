"""Registro das fontes disponíveis. Para adicionar uma nova fonte, crie uma
subclasse de `Source` e registre-a aqui com o mesmo nome usado no config.yaml."""

from jobcrawler.sources.base import Source, SourceResult
from jobcrawler.sources.github_issues import GitHubIssuesSource
from jobcrawler.sources.gupy import GupySource
from jobcrawler.sources.himalayas import HimalayasSource
from jobcrawler.sources.jobicy import JobicySource
from jobcrawler.sources.linkedin import LinkedInSource
from jobcrawler.sources.remoteok import RemoteOkSource
from jobcrawler.sources.remotive import RemotiveSource
from jobcrawler.sources.weworkremotely import WeWorkRemotelySource

REGISTRY: dict[str, type[Source]] = {
    cls.name: cls
    for cls in (GupySource, GitHubIssuesSource, LinkedInSource,
                HimalayasSource, JobicySource, RemotiveSource, RemoteOkSource,
                WeWorkRemotelySource)
}

__all__ = ["REGISTRY", "Source", "SourceResult"]
