from datetime import datetime
from typing import Any, Dict, List, Optional, Annotated

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

# Luồng dữ liệu (Flow)
# 1. Client gửi POST /memberships với payload:
#    {"card_number": "...", "customer_id": 123}
# 2. API mở session MySQL và dùng SELECT + .first() để kiểm tra tồn tại khách hàng:
#    db.query(CustomerModel).filter(CustomerModel.id == payload.customer_id).first()
# 3. Nếu customer không tồn tại => raise HTTPException(404) trả về JSON 6 trường.
# 4. Nếu customer tồn tại => tiếp tục dùng SELECT + .first() kiểm tra card_number đã tồn tại chưa.
# 5. Nếu card_number đã tồn tại => raise HTTPException(400) trả về JSON 6 trường.
# 6. Nếu dữ liệu hợp lệ => tạo MembershipModel, db.add(membership), db.commit(), db.refresh(membership)
# 7. Trả về 201 Created với cấu trúc JSON 6 trường đồng nhất.

SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:password@localhost:3306/crm_db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()

app = FastAPI()

def get_current_timestamp() -> str:
    return datetime.now().isoformat() + "Z"

class MembershipRequest(BaseModel):
    card_number: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=50
        )
    ]
    customer_id: int

class MembershipData(BaseModel):
    id: int
    card_number: str
    customer_id: int

class ResponseSchema(BaseModel):
    status_code: int
    success: bool
    message: str
    data: Optional[Any]
    errors: Optional[List[Dict[str, str]]]
    timestamp: str = Field(default_factory=get_current_timestamp)

class CustomerModel(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)

class MembershipModel(Base):
    __tablename__ = "memberships"
    id = Column(Integer, primary_key=True, index=True)
    card_number = Column(String(50), unique=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)

def build_response(
    status_code: int,
    success: bool,
    message: str,
    data: Optional[Any] = None,
    errors: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    return {
        "status_code": status_code,
        "success": success,
        "message": message,
        "data": data,
        "errors": errors,
        "timestamp": get_current_timestamp(),
    }

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail or {}
    if isinstance(detail, dict):
        message = detail.get("message", str(detail))
        errors = detail.get("errors")
    else:
        message = str(detail)
        errors = None

    return JSONResponse(
        status_code=exc.status_code,
        content=build_response(
            status_code=exc.status_code,
            success=False,
            message=message,
            data=None,
            errors=errors,
        ),
    )

@app.post(
    "/memberships",
    response_model=ResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo thẻ thành viên VIP cho khách hàng",
)
def create_membership(payload: MembershipRequest) -> Dict[str, Any]:
    db: Session = SessionLocal()
    try:
        customer = db.query(CustomerModel).filter(CustomerModel.id == payload.customer_id).first()
        if customer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "message": "Khách hàng không tồn tại trên hệ thống",
                    "errors": [
                        {
                            "field": "customer_id",
                            "message": "customer_id không tồn tại trong bảng customers",
                        }
                    ],
                },
            )

        existing_membership = db.query(MembershipModel).filter(
            MembershipModel.card_number == payload.card_number
        ).first()
        if existing_membership is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Mã số thẻ thành viên này đã được sử dụng",
                    "errors": [
                        {
                            "field": "card_number",
                            "message": "card_number đã tồn tại",
                        }
                    ],
                },
            )

        membership = MembershipModel(
            card_number=payload.card_number,
            customer_id=payload.customer_id,
        )
        db.add(membership)
        db.commit()
        db.refresh(membership)

        return build_response(
            status_code=status.HTTP_201_CREATED,
            success=True,
            message="Thẻ thành viên VIP đã được tạo thành công",
            data=MembershipData(
                id=membership.id,
                card_number=membership.card_number,
                customer_id=membership.customer_id,
            ).dict(),
            errors=None,
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Mã số thẻ thành viên này đã được sử dụng",
                "errors": [
                    {
                        "field": "card_number",
                        "message": "card_number đã được đăng ký bởi thẻ khác",
                    }
                ],
            },
        )
    finally:
        db.close()