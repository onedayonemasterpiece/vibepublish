"""Regression for Telegram archive DOCUMENT upload; no live Telegram or waiting."""
import pytest

from social_operations.execution_budgets import command_seconds, execution_seconds


@pytest.mark.parametrize("byte_size,expected_seconds", [
    (16_667_815, 90),
    (40_185_769, 161),
    (63_904_669, 256),  # This real PDF twice exhausted the old 90-second budget.
    (128 * 1024 * 1024, 537),
])
def test_archive_pdf_djvu_upload_uses_bounded_verified_byte_budget(byte_size, expected_seconds):
    plan = {"provider": "telegram", "workload": "media_store",
            "assets": [{"role": "document", "mime": "application/pdf", "size": byte_size}]}
    assert execution_seconds(plan) == expected_seconds
    assert command_seconds([plan]) == expected_seconds + 30
    plan["assets"][0]["mime"] = "image/vnd.djvu"
    assert execution_seconds(plan) == expected_seconds


def test_normal_media_publication_and_images_keep_90_second_budget():
    document = {"role": "document", "mime": "application/pdf", "size": 63_904_669}
    for override in ({"workload": "publication"}, {"provider": "vk"},
                     {"assets": [{"role": "image", "mime": "image/png", "size": 63_904_669}]}):
        plan = {"provider": "telegram", "workload": "media_store", "assets": [document], **override}
        assert execution_seconds(plan) == 90
