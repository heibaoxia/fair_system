import io
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.api import files
from app.database import Base


class UploadModuleFileDependencyValidationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = TestingSessionLocal()

        owner = models.Member(name="Owner", tel="13800000000", is_active=True)
        self.db.add(owner)
        self.db.flush()

        project = models.Project(
            name="Demo Project",
            description="",
            created_by=owner.id,
        )
        self.db.add(project)
        self.db.flush()

        preceding_module = models.Module(
            name="Preceding",
            project_id=project.id,
            status="已完成",
            assigned_to=owner.id,
        )
        dependent_module = models.Module(
            name="Dependent",
            project_id=project.id,
            status="开发中",
            assigned_to=owner.id,
        )
        self.db.add_all([preceding_module, dependent_module])
        self.db.flush()

        dependency = models.FileDependency(
            preceding_module_id=preceding_module.id,
            dependent_module_id=dependent_module.id,
        )
        self.db.add(dependency)
        self.db.commit()

        self.owner_id = owner.id
        self.owner_context = SimpleNamespace(
            account=SimpleNamespace(is_super_account=False),
            acting_member=owner,
        )
        self.preceding_module_id = preceding_module.id
        self.dependent_module_id = dependent_module.id

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_upload_is_blocked_when_preceding_module_has_no_approved_file(self):
        upload = UploadFile(filename="deliverable.txt", file=io.BytesIO(b"content"))

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(files, "UPLOAD_DIR", temp_dir):
                with self.assertRaises(HTTPException) as exc_info:
                    files.upload_module_file(
                        module_id=self.dependent_module_id,
                        file=upload,
                        context=self.owner_context,
                        db=self.db,
                    )

        self.assertEqual(exc_info.exception.status_code, 403)
        self.assertEqual(
            exc_info.exception.detail,
            "该模块的前置模块尚未全部完成审核，暂不能提交文件。",
        )

    def test_approve_reports_newly_unlocked_downstream_modules(self):
        dependent_module = self.db.query(models.Module).filter(
            models.Module.id == self.dependent_module_id
        ).first()
        dependent_module.status = "待分配"

        pending_file = models.ModuleFile(
            module_id=self.preceding_module_id,
            uploaded_by=self.owner_id,
            file_path="uploads/module_1/result.txt",
            file_name="result.txt",
            status="Pending",
        )
        self.db.add(pending_file)
        self.db.commit()

        result = files._review_file(
            file_id=pending_file.id,
            action="approve",
            context=self.owner_context,
            db=self.db,
        )

        self.assertEqual(result["message"], "审核通过！该模块正式完工。 以下后置模块已解锁：Dependent")
        self.assertEqual(result["unlocked_modules"], ["Dependent"])


if __name__ == "__main__":
    unittest.main()
