from enum import Enum

class JapaneseLevel(str, Enum):
    NONE = "none"
    BASIC = "basic"
    CONVERSATIONAL = "conversational"
    BUSINESS = "business"
    FLUENT = "fluent"

class EnglishLevel(str, Enum):
    NONE = "none"
    BASIC = "basic"
    CONVERSATIONAL = "conversational"
    BUSINESS = "business"
    FLUENT = "fluent"

class ApplicantLocation(str, Enum):
    APPLY_FROM_ABROAD = "apply_from_abroad"
    JAPAN_ONLY = "japan_residents_only"

class Seniority(str, Enum):
    INTERN = "intern"
    JUNIOR = "junior"
    INTERMEDIATE = "intermediate"
    SENIOR = "senior"

class Salary(str, Enum):
    ANY = ""
    MILLION_4 = "4000000"
    MILLION_6 = "6000000"
    MILLION_8 = "8000000"
    MILLION_10 = "10000000"
