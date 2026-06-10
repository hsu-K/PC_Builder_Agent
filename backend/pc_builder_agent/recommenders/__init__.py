"""
External component recommender 接入點。

「要推薦哪些零組件候選」可委派給外部 recommender(例如同學的實作)。本套件提供:
- `external_adapter.example_recommend`:**範例/參考**實作(請替換成同學的正式 recommender)。
- 啟用方式(擇一):
    1) 環境變數(零改碼,推薦):
         PC_BUILDER_EXTERNAL_RECOMMENDER="pc_builder_agent.recommenders.classmate:recommend"
    2) 程式註冊:
         from pc_builder_agent.tools.ecommerce_db import set_external_component_recommender
         import pc_builder_agent.tools.ecommerce_db as db
         set_external_component_recommender(my_recommend)
         db.USE_EXTERNAL_COMPONENT_RECOMMENDER = True

外部函式介面:`recommend(context: dict) -> list[dict]`(見 external_adapter 的 docstring)。
"""

from pc_builder_agent.recommenders.external_adapter import (
    example_recommend,
    CONTEXT_FIELDS,
    OPTION_FIELDS,
)

__all__ = ["example_recommend", "CONTEXT_FIELDS", "OPTION_FIELDS"]
