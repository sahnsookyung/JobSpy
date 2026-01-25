from enum import Enum

class FilterEnum(str, Enum):
    key: str  # subclasses override

    @property
    def pair(self) -> tuple[str, str]:
        return (self.key, self.value)

    @property
    def full_id(self) -> str:
        k, v = self.pair
        return f"{k}-{v}"

    @property
    def selector(self) -> str:
        # Attribute selector avoids CSS escaping issues for spaces, '/', '+', etc.
        return f"[id='{self.full_id}']"

class JdApplicantLocation(FilterEnum):
    key = "candidate_location"
    ANYWHERE = "candidate_location_anywhere"
    JAPAN_ONLY = "candidate_location_japan_only"


class JdJapaneseLevel(FilterEnum):
    key = "japanese_level_enum"
    NOT_REQUIRED = "japanese_level_not_required"
    BUSINESS = "japanese_level_business_level"
    CONVERSATIONAL = "japanese_level_conversational"
    FLUENT = "japanese_level_fluent"


class JdRemoteWork(FilterEnum):
    key = "remote_level"
    PARTIAL_REMOTE = "remote_level_partial"
    ANYWHERE_IN_JAPAN = "remote_level_full_japan"
    NO_REMOTE = "remote_level_none"
    WORLDWIDE = "remote_level_full_worldwide"
    FULL_REMOTE = "remote_level_around_office"


class JdSeniority(FilterEnum):
    key = "seniority_level"
    SENIOR = "seniority_level_senior"
    MID_LEVEL = "seniority_level_mid_level"
    JUNIOR = "seniority_level_junior"
    NEW_GRAD = "seniority_level_new_grad"


class JdSalary(FilterEnum):
    key = "salary_tags"
    HAS_SALARY_RANGE = "has_salary_range"
    OVER_6M = "salary_over_6m"
    OVER_8M = "salary_over_8m"
    OVER_10M = "salary_over_10m"


class JdJobType(FilterEnum):
    key = "job_type_names"
    ENGINEERING = "Engineering"
    DESIGN = "Design"
    OTHER = "Other"


class JdOfficeLocation(FilterEnum):
    key = "location"
    TOKYO = "Tokyo"
    OSAKA = "Osaka"
    OTHER = "Other"


class JdCompanyType(FilterEnum):
    key = "company_is_startup"
    STARTUP = "true"


class JdEnglishLevel(FilterEnum):
    key = "english_level_enum"
    BUSINESS = "english_level_business_level"
    FLUENT = "english_level_fluent"


class JdSkill(FilterEnum):
    key = "skill_names"
    PYTHON = "Python"
    TYPESCRIPT = "Typescript"
    BACKEND = "Backend"
    GO = "Go"
    REACT = "React"
    KUBERNETES = "Kubernetes"
    DOCKER = "Docker"
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
