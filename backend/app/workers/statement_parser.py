"""
Statement Parser Worker.

Consumes: statement.uploaded  (SQS)
Produces: statement.parsed    (SQS)

Flow per message:
  1. Download file from S3
  2. Parse CSV or PDF into list[ParsedTransaction]
  3. Bulk-insert transactions (status=pending categorisation)
  4. Update BankStatement status → completed | failed
  5. Publish statement.parsed event for the AI categoriser
"""
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import engine
from app.sqs.producer import sqs_producer
from app.sqs.queues import Queues
from app.services.statement_service import (
    bulk_insert_transactions,
    mark_completed,
    mark_failed,
    mark_processing,
)
from app.utils.csv_parser import CSVParseError, parse_csv
from app.utils.pdf_parser import PDFParseError, parse_pdf
from app.utils.s3 import download_file
from app.workers.base_worker import BaseWorker

logger = structlog.get_logger(__name__)


class StatementParserWorker(BaseWorker):
    """SQS consumer that parses uploaded bank statement files."""

    queue_url_fn = Queues.statement_uploaded

    async def process_message(self, payload: dict) -> None:
        statement_id_str = payload["statement_id"]
        user_id_str = payload["user_id"]
        s3_key = payload["s3_key"]
        file_type = payload["file_type"]

        log = logger.bind(statement_id=statement_id_str, file_type=file_type)
        log.info("Processing statement")

        AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with AsyncSessionLocal() as db:
            async with db.begin():
                import uuid
                statement_id = uuid.UUID(statement_id_str)
                user_id = uuid.UUID(user_id_str)

                await mark_processing(db, statement_id)

            try:
                # 1. Download from S3
                file_bytes = await download_file(s3_key)
                log.info("File downloaded", size=len(file_bytes))

                # 2. Parse
                if file_type == "csv":
                    parsed = parse_csv(file_bytes)
                elif file_type == "pdf":
                    parsed = parse_pdf(file_bytes)
                else:
                    raise ValueError(f"Unknown file_type: {file_type}")

                log.info("File parsed", transaction_count=len(parsed))

                # 3. Bulk-insert transactions + mark completed
                async with db.begin():
                    row_count = await bulk_insert_transactions(
                        db, user_id, statement_id, parsed
                    )
                    await mark_completed(db, statement_id, row_count)

                # 4. Publish to next stage
                await sqs_producer.send(
                    queue_url=Queues.statement_parsed(),
                    payload={
                        "statement_id": statement_id_str,
                        "user_id": user_id_str,
                        "transaction_count": row_count,
                    },
                )
                log.info("statement.parsed event published")

            except (CSVParseError, PDFParseError, ValueError) as exc:
                async with db.begin():
                    await mark_failed(db, statement_id, str(exc))
                log.error("Parse failed", error=str(exc))

            except Exception as exc:
                async with db.begin():
                    await mark_failed(db, statement_id, f"Unexpected error: {exc}")
                log.exception("Unexpected error during statement processing")
                raise  # re-raise so SQS visibility timeout handles retry
