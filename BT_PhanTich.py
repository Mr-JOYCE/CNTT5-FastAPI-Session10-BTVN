"""
API Kiểm tra mã vận đơn

Phần 1: Phân tích Input/Output
- Input: shipment_id (kiểu int) được truyền qua URL /shipments/{shipment_id}.
- Output thành công: JSON chứa thông tin vận đơn khi tìm thấy.
- Output thất bại: JSON lỗi chuẩn RESTful với mã 404 và thông báo rõ ràng khi không tìm thấy.

Phần 2: So sánh & Lựa chọn giải pháp

| Tiêu chí | .all() + lọc bằng Python | .first() trực tiếp từ DB |
|---|---|---|
| Số bản ghi kéo lên RAM | Kéo toàn bộ 100.000 bản ghi lên RAM | Chỉ lấy đúng 1 bản ghi phù hợp |
| SQL sinh ra | SELECT * FROM shipments | SELECT ... FROM shipments WHERE id = ? LIMIT 1 |
| Tốc độ khi dữ liệu lớn | Chậm, tốn bộ nhớ, tăng tải cho server | Nhanh, nhẹ, tối ưu |
| Bối cảnh phù hợp | Khi cần lấy toàn bộ dữ liệu để xử lý tập thể | Khi chỉ cần kiểm tra tồn tại hoặc lấy 1 bản ghi |

Kết luận lựa chọn:
Dùng .first() trực tiếp khi chỉ cần tìm một bản ghi duy nhất để giảm tải RAM, giảm thời gian phản hồi và giảm tải cho Database.
"""

import os
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:password@localhost:3306/shipment_db",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, index=True)
    shipment_code = Column(String(100), nullable=False, unique=True, index=True)
    status = Column(String(50), nullable=False)
    destination = Column(String(100), nullable=True)


class ShipmentOut(BaseModel):
    id: int
    shipment_code: str
    status: str
    destination: Optional[str] = None


class ErrorResponse(BaseModel):
    error: str
    message: str


app = FastAPI(title="Shipment Lookup API")


# Tạo bảng mẫu nếu database đã sẵn sàng.
# Trong môi trường thật, migrate bằng Alembic hoặc SQLAlchemy migrations.
Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get(
    "/shipments/{shipment_id}",
    response_model=ShipmentOut,
    responses={404: {"model": ErrorResponse, "description": "Không tìm thấy vận đơn"}},
)
def get_shipment(shipment_id: int, db: Session = Depends(get_db)):
    """
    Truy vấn một vận đơn theo id bằng phương thức .first() để chặn sớm ở database.
    Đây là giải pháp tối ưu vì chỉ lấy đúng 1 bản ghi, không kéo toàn bộ dữ liệu lên RAM.
    """

    shipment = (
        db.query(Shipment)
        .filter(Shipment.id == shipment_id)
        .first()
    )

    if shipment is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "shipment_not_found",
                "message": f"Không tìm thấy mã vận đơn với id={shipment_id}",
            },
        )

    return ShipmentOut(
        id=shipment.id,
        shipment_code=shipment.shipment_code,
        status=shipment.status,
        destination=shipment.destination,
    )


@app.get("/health")
def health_check():
    return {"status": "ok"}
