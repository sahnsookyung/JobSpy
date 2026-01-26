# japandev_enums.py
from __future__ import annotations

from enum import Enum, nonmember


class FilterEnum(str, Enum):
    """
    JapanDev filter options are clicked via a DOM id of the form: "{_key}-{token}".
    
    Subclasses define:
      - _key: the left side of the id. Wrapped in nonmember() so it remains a 
              class attribute and does NOT become an enum member.
      - value: the right side (token) (the enum member value).
    """
    _key: str  # subclasses override

    @property
    def pair(self) -> tuple[str, str]:
        # correctly reads the class-level _key attribute
        return (type(self)._key, self.value)

    @property
    def full_id(self) -> str:
        k, v = self.pair
        return f"{k}-{v}"

    @property
    def selector(self) -> str:
        # Attribute selector avoids CSS escaping issues for spaces, '/', '+', etc.
        return f"[id='{self.full_id}']"



class JdApplicantLocation(FilterEnum):
    _key = nonmember("candidate_location")
    ANYWHERE = "candidate_location_anywhere"
    JAPAN_ONLY = "candidate_location_japan_only"


class JdJapaneseLevel(FilterEnum):
    _key = nonmember("japanese_level_enum")
    NOT_REQUIRED = "japanese_level_not_required"
    BUSINESS = "japanese_level_business_level"
    CONVERSATIONAL = "japanese_level_conversational"
    FLUENT = "japanese_level_fluent"


class JdEnglishLevel(FilterEnum):
    _key = nonmember("english_level_enum")
    BUSINESS = "english_level_business_level"
    FLUENT = "english_level_fluent"


class JdRemoteWork(FilterEnum):
    _key = nonmember("remote_level")
    PARTIAL_REMOTE = "remote_level_partial"
    ANYWHERE_IN_JAPAN = "remote_level_full_japan"
    NO_REMOTE = "remote_level_none"
    WORLDWIDE = "remote_level_full_worldwide"
    FULL_REMOTE = "remote_level_around_office"


class JdSeniority(FilterEnum):
    _key = nonmember("seniority_level")
    SENIOR = "seniority_level_senior"
    MID_LEVEL = "seniority_level_mid_level"
    JUNIOR = "seniority_level_junior"
    NEW_GRAD = "seniority_level_new_grad"


class JdSalary(FilterEnum):
    _key = nonmember("salary_tags")
    HAS_SALARY_RANGE = "has_salary_range"
    OVER_6M = "salary_over_6m"
    OVER_8M = "salary_over_8m"
    OVER_10M = "salary_over_10m"


class JdJobType(FilterEnum):
    _key = nonmember("job_type_names")
    ENGINEERING = "Engineering"
    DESIGN = "Design"
    OTHER = "Other"


class JdOfficeLocation(FilterEnum):
    _key = nonmember("location")
    TOKYO = "Tokyo"
    OSAKA = "Osaka"
    OTHER = "Other"


class JdCompanyType(FilterEnum):
    _key = nonmember("company_is_startup")
    STARTUP = "true"


class JdSkill(FilterEnum):
    _key = nonmember("skill_names")
    PYTHON = "Python"
    TYPESCRIPT = "Typescript"
    BACKEND = "Backend"
    GO = "Go"
    REACT = "React"
    KUBERNETES = "Kubernetes"
    DOCKER = "Docker"
    CPP = "C++"
    JAVA = "Java"
    SECURITY = "Security"
    ENG_OTHER = "Eng - Other"
    WEB_FULLSTACK = "Web / Full-stack"
    AWS = "AWS"
    JAVASCRIPT = "Javascript"
    MYSQL = "MySQL"
    GRPC = "gRPC"
    INFRA = "Infra"
    ML = "ML"
    QA = "QA"
    RUBY = "Ruby"
