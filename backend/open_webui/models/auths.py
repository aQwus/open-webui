import logging
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_db
from open_webui.models.users import UserModel, UserProfileImageResponse, Users
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, String, Text

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# DB MODEL
####################


class Auth(Base):
    __tablename__ = "auth"

    id = Column(String, primary_key=True, unique=True)
    email = Column(String)
    password = Column(Text)
    active = Column(Boolean)


class AuthModel(BaseModel):
    id: str
    email: str
    password: str
    active: bool = True


####################
# Forms
####################


class Token(BaseModel):
    token: str
    token_type: str


class ApiKey(BaseModel):
    api_key: Optional[str] = None


class SigninResponse(Token, UserProfileImageResponse):
    pass


class SigninForm(BaseModel):
    email: str
    password: str


class LdapForm(BaseModel):
    user: str
    password: str


class ProfileImageUrlForm(BaseModel):
    profile_image_url: str


class UpdatePasswordForm(BaseModel):
    password: str
    new_password: str


class SignupForm(BaseModel):
    name: str
    email: str
    password: str
    profile_image_url: Optional[str] = "/user.png"


class AddUserForm(SignupForm):
    role: Optional[str] = "pending"


class AuthsTable:
    def _find_existing_user_id(self, email: str) -> Optional[str]:
        """
        Check Supabase 'users' table for existing user_id associated with this email.
        
        Strategy: Query users table directly for user record with this email.
        If Supabase is unavailable, raises exception to block signup.
        
        Returns:
            Existing user_id if found, None if truly new user
            
        Raises:
            Exception if Supabase is unavailable (to ensure one user per email)
        """
        from open_webui.services.supabase_service import supabase_service
        
        if not supabase_service.is_enabled():
            raise Exception("User registration requires Supabase to be available")
        
        try:
            # Query Supabase users table for existing user with this email
            response = (supabase_service.client.table('users')
                .select('user_id')
                .eq('user_email', email.lower())
                .limit(1)
                .execute())
            
            if response.data and len(response.data) > 0:
                existing_id = response.data[0].get('user_id')
                log.info(f"Found existing user_id in Supabase users table: {existing_id}")
                return existing_id
            else:
                log.debug(f"No existing user found for {email} - this is a new user")
                return None
                
        except Exception as e:
            log.error(f"Error checking Supabase users table: {e}")
            # Do NOT fallback - raise exception to block signup
            raise Exception(f"User registration temporarily unavailable: {str(e)}")
    
    def insert_new_auth(
        self,
        email: str,
        password: str,
        name: str,
        profile_image_url: str = "/user.png",
        role: str = "pending",
        oauth: Optional[dict] = None,
    ) -> Optional[UserModel]:
        with get_db() as db:
            log.info("insert_new_auth")

            # Try to find existing user_id from Supabase
            try:
                existing_user_id = self._find_existing_user_id(email)
                
                if existing_user_id:
                    log.info(f"Reusing existing user_id for {email}: {existing_user_id}")
                    id = existing_user_id
                    
                    # Update updated_at timestamp for returning user
                    try:
                        from open_webui.services.supabase_service import supabase_service
                        from datetime import datetime
                        supabase_service.client.table('users').update({
                            'updated_at': datetime.now().isoformat()
                        }).eq('user_id', id).execute()
                        log.info(f"Updated timestamp for returning user: {email}")
                    except Exception as e:
                        log.warning(f"Failed to update timestamp (non-blocking): {e}")
                else:
                    log.info(f"Creating new user_id for {email}")
                    id = str(uuid.uuid4())
            except Exception as e:
                # Supabase unavailable - block signup
                log.error(f"Cannot create user, Supabase unavailable: {e}")
                raise  # Re-raise to propagate HTTP 503 error

            auth = AuthModel(
                **{"id": id, "email": email, "password": password, "active": True}
            )
            result = Auth(**auth.model_dump())
            db.add(result)

            user = Users.insert_new_user(
                id, name, email, profile_image_url, role, oauth=oauth
            )

            db.commit()
            db.refresh(result)

            if result and user:
                # Sync new user to Supabase users table
                try:
                    if not existing_user_id:  # Only for truly new users
                        from open_webui.services.supabase_service import supabase_service
                        from datetime import datetime
                        current_time = datetime.now().isoformat()
                        
                        supabase_service.client.table('users').insert({
                            'user_id': id,
                            'user_email': email.lower(),
                            'created_at': current_time,
                            'updated_at': current_time,
                        }).execute()
                        log.info(f"Synced new user to Supabase: {email}")
                except Exception as e:
                    log.warning(f"Failed to sync user to Supabase (non-blocking): {e}")
                
                return user
            else:
                return None

    def authenticate_user(
        self, email: str, verify_password: callable
    ) -> Optional[UserModel]:
        log.info(f"authenticate_user: {email}")

        user = Users.get_user_by_email(email)
        if not user:
            return None

        try:
            with get_db() as db:
                auth = db.query(Auth).filter_by(id=user.id, active=True).first()
                if auth:
                    if verify_password(auth.password):
                        return user
                    else:
                        return None
                else:
                    return None
        except Exception:
            return None

    def authenticate_user_by_api_key(self, api_key: str) -> Optional[UserModel]:
        log.info(f"authenticate_user_by_api_key: {api_key}")
        # if no api_key, return None
        if not api_key:
            return None

        try:
            user = Users.get_user_by_api_key(api_key)
            return user if user else None
        except Exception:
            return False

    def authenticate_user_by_email(self, email: str) -> Optional[UserModel]:
        log.info(f"authenticate_user_by_email: {email}")
        try:
            with get_db() as db:
                auth = db.query(Auth).filter_by(email=email, active=True).first()
                if auth:
                    user = Users.get_user_by_id(auth.id)
                    return user
        except Exception:
            return None

    def update_user_password_by_id(self, id: str, new_password: str) -> bool:
        try:
            with get_db() as db:
                result = (
                    db.query(Auth).filter_by(id=id).update({"password": new_password})
                )
                db.commit()
                return True if result == 1 else False
        except Exception:
            return False

    def update_email_by_id(self, id: str, email: str) -> bool:
        try:
            with get_db() as db:
                result = db.query(Auth).filter_by(id=id).update({"email": email})
                db.commit()
                return True if result == 1 else False
        except Exception:
            return False

    def delete_auth_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                # Delete User
                result = Users.delete_user_by_id(id)

                if result:
                    db.query(Auth).filter_by(id=id).delete()
                    db.commit()

                    return True
                else:
                    return False
        except Exception:
            return False


Auths = AuthsTable()
