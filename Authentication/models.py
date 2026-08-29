from pydantic import AnyHttpUrl, BaseModel, EmailStr, Field, field_validator, model_validator


ALLOWED_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "icloud.com",
    "me.com",
    "mac.com",
}


def validate_supported_email(email: EmailStr):
    if email.lower().rsplit("@", 1)[-1] not in ALLOWED_EMAIL_DOMAINS:
        raise ValueError("Use a Google, Outlook, or Apple iCloud email address")
    return email.lower()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def supported_email(cls, email):
        return validate_supported_email(email)


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    otp: str = Field(pattern=r"^\d{6}$")


class EmailRequest(BaseModel):
    email: EmailStr


class LoginRequest(EmailRequest):
    password: str


class ResetPasswordRequest(VerifyEmailRequest):
    new_password: str = Field(min_length=8, max_length=128)


class GoogleLoginRequest(BaseModel):
    credential: str


class UpdateUserRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    first_name: str | None = Field(default=None, max_length=50)
    last_name: str | None = Field(default=None, max_length=50)
    linkedin_url: AnyHttpUrl | None = None
    github_url: AnyHttpUrl | None = None
    phone_number: str | None = Field(default=None, pattern=r"^\+?[0-9 ()-]{7,20}$")
    address: str | None = Field(default=None, max_length=300)
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("linkedin_url", "github_url", "phone_number", mode="before")
    @classmethod
    def blank_optional_value(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def password_pair(self):
        if self.new_password and not self.current_password:
            raise ValueError("Current password is required to set a new password")
        profile_fields = (
            self.name,
            self.first_name,
            self.last_name,
            self.linkedin_url,
            self.github_url,
            self.phone_number,
            self.address,
        )
        if not any(value is not None for value in profile_fields) and self.new_password is None:
            raise ValueError("Provide profile details or a new password")
        return self


class UserResponse(BaseModel):
    id: str
    name: str
    email: EmailStr
    provider: str
    is_verified: bool
    first_name: str | None = None
    last_name: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    phone_number: str | None = None
    address: str | None = None
    profile_picture_url: str | None = None
    role: str = "user"
    is_active: bool = True
    blocked_projects: list[str] = Field(default_factory=list)