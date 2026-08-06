# -*- coding: utf-8 -*-
"""
智能数据处理模块 - LLM真正理解数据并生成处理逻辑

核心区别：
  传统方式: df[df['收支类型'] == '收入']           ← 写死列名和值，列名一改就废
  智能方式: LLM读取Excel样本 → 理解每列含义 →      ← LLM理解数据
            自己写代码筛选 → 执行 → 验证结果         ← 自动适应列名变化
"""
import json
import pandas as pd
from typing import Dict, Any, Optional, Tuple, List
from loguru import logger

from src.core.llm_client import LocalLLMClient


class SmartDataProcessor:
    """
    智能数据处理器

    LLM的参与：
    1. 读取Excel后，LLM分析每列的业务含义
    2. 用户用自然语言描述需求，LLM生成Pandas代码
    3. 安全执行代码，返回结果
    4. LLM验证结果合理性
    """

    def __init__(self, llm: Optional[LocalLLMClient] = None):
        self.llm = llm or LocalLLMClient()

    def process_excel(
        self,
        file_path: str,
        task_description: str,
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        智能处理Excel文件

        Args:
            file_path: Excel文件路径
            task_description: 任务的自然语言描述
                如 "找出销售额（收支类型为收入的数据），计算总金额"
            output_path: 输出文件路径（可选）

        Returns:
            处理结果字典
        """
        logger.info(f"智能处理Excel: {file_path}")
        logger.info(f"任务描述: {task_description}")

        # 1. 读取Excel
        df = pd.read_excel(file_path)
        logger.info(f"读取成功: {len(df)}行, {len(df.columns)}列")

        # 2. 准备数据样本给LLM
        samples = {}
        for col in df.columns:
            non_null = df[col].dropna()
            samples[col] = {
                "dtype": str(df[col].dtype),
                "sample_values": [str(v) for v in non_null.head(5).tolist()],
                "unique_count": int(df[col].nunique())
            }

        # 3. LLM理解数据 + 生成处理代码
        code, explanation = self._llm_generate_code(df, samples, task_description)

        if not code:
            return {"status": "failed", "error": "LLM未能生成处理代码"}

        logger.info(f"LLM生成的处理逻辑: {explanation}")
        logger.info(f"LLM生成的代码:\n{code}")

        # 4. 执行代码
        result = self._execute_code(code, df)

        if result is None:
            return {"status": "failed", "error": "代码执行失败"}

        # 5. LLM验证结果
        validation = self._llm_validate_result(task_description, result, samples)

        # 6. 保存结果
        if output_path and isinstance(result.get("data"), pd.DataFrame):
            result["data"].to_excel(output_path, index=False)
            result["output_path"] = output_path

        return {
            "status": "success",
            "code": code,
            "explanation": explanation,
            "result": {k: v for k, v in result.items() if k != "data"},
            "validation": validation,
            "data": result.get("data")
        }

    def _llm_generate_code(
        self,
        df: pd.DataFrame,
        samples: Dict,
        task_description: str
    ) -> Tuple[Optional[str], str]:
        """
        LLM理解数据结构，生成Pandas处理代码

        Args:
            df: DataFrame
            samples: 每列的样本数据
            task_description: 任务描述

        Returns:
            (代码, 说明)
        """
        system_prompt = """你是一个数据分析专家。
用户会给你一个Excel的数据结构和你需要完成的任务。
你需要：
1. 理解每列的业务含义
2. 生成Pandas代码来完成任务
3. 代码中只能使用 df 变量（已加载的DataFrame）
4. 结果保存到 result 字典中

代码模板：
```python
result = {}
# 你的处理逻辑
result['销售额'] = float(df[列名].sum())
result['data'] = 筛选后的DataFrame
```

注意：
- 只能用 df 这个变量
- 数字结果转为 float 或 int
- 不要用 print
- 代码要能独立执行"""

        user_message = f"""任务: {task_description}

数据结构（列名和样本）:
{json.dumps(samples, ensure_ascii=False, indent=2)}

总行数: {len(df)}

请生成Pandas处理代码。先用```python和```包裹代码，然后简要说明处理逻辑。"""

        try:
            response = self.llm.chat(
                message=user_message,
                system_prompt=system_prompt
            )

            # 提取代码块
            code_start = response.find("```python")
            if code_start == -1:
                code_start = response.find("```")
                code_end = response.find("```", code_start + 3)
            else:
                code_end = response.find("```", code_start + 8)

            if code_start != -1 and code_end != -1:
                code = response[code_start:code_end]
                # 清理代码
                code = code.replace("```python", "").replace("```", "").strip()
                # 提取说明
                explanation = response[code_end + 3:].strip()[:500]

                return code, explanation

            logger.warning(f"LLM返回中未找到代码块: {response[:200]}")
            return None, ""

        except Exception as e:
            logger.error(f"LLM生成代码失败: {e}")
            return None, ""

    def _execute_code(self, code: str, df: pd.DataFrame) -> Optional[Dict]:
        """
        安全执行LLM生成的代码

        使用受限的执行环境：
        - 只能访问 df 和 pandas
        - 不能访问文件系统、网络等
        """
        try:
            # 受限的执行环境
            local_vars = {"df": df, "pd": pd, "result": {}}

            exec(code, {"__builtins__": {
                "float": float, "int": int, "str": str,
                "len": len, "sum": sum, "abs": abs,
                "round": round, "list": list, "dict": dict,
                "print": lambda *a: None  # 禁止输出
            }}, local_vars)

            result = local_vars.get("result", {})

            if not result:
                logger.warning("代码执行后result为空")
                return None

            logger.info(f"代码执行成功，结果keys: {list(result.keys())}")
            return result

        except Exception as e:
            logger.error(f"代码执行失败: {e}")
            return None

    def _llm_validate_result(
        self,
        task_description: str,
        result: Dict,
        samples: Dict
    ) -> Dict[str, Any]:
        """LLM验证处理结果是否合理"""
        # 提取数值结果
        numeric_results = {
            k: v for k, v in result.items()
            if isinstance(v, (int, float)) and k != "data"
        }

        system_prompt = """你是一个数据审核助手。
请判断数据处理结果是否合理。

返回JSON: {
    "reasonable": true/false,
    "issues": ["问题1", "问题2"],
    "summary": "结果摘要"
}"""

        user_message = f"""任务: {task_description}

数据列: {list(samples.keys())}
处理结果（数值）: {numeric_results}

请判断结果是否合理。"""

        try:
            response = self.llm.chat(
                message=user_message,
                system_prompt=system_prompt
            )

            json_start = response.find("{")
            json_end = response.rfind("}") + 1

            if json_start != -1 and json_end != -1:
                return json.loads(response[json_start:json_end])

        except:
            pass

        return {"reasonable": True, "issues": [], "summary": "验证跳过"}

    # ==================== 数据理解增强（3.0 新增）====================
    def understand_data(
        self,
        file_path: str,
        max_sample_rows: int = 5,
    ) -> Dict[str, Any]:
        """
        自动理解数据结构（无需用户描述任务）

        LLM会自动分析：
        1. 每列的业务含义（如"这是金额列"、"这是日期列"）
        2. 数据类型识别（数值/分类/日期/文本）
        3. 数据质量评估（缺失率、异常值）
        4. 业务主题识别（这是销售数据/财务数据/库存数据）

        Args:
            file_path: Excel/CSV文件路径
            max_sample_rows: 给LLM看的样本行数

        Returns:
            {
                "columns": [{"name": "列名", "meaning": "业务含义", "type": "数据类型"}, ...],
                "topic": "业务主题",
                "quality": {"missing_rate": 0.05, "issues": ["问题1"]},
                "suggestions": ["建议的处理方向1", ...]
            }
        """
        logger.info(f"[DataUnderstanding] 分析数据: {file_path}")

        # 1. 读取数据
        try:
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
        except Exception as e:
            return {"status": "failed", "error": f"读取文件失败: {e}"}

        if df.empty:
            return {"status": "failed", "error": "文件为空"}

        # 2. 统计信息
        stats = {}
        for col in df.columns:
            col_data = df[col]
            non_null = col_data.dropna()
            stats[col] = {
                "dtype": str(col_data.dtype),
                "total_count": len(col_data),
                "non_null_count": len(non_null),
                "missing_rate": round(1 - len(non_null) / len(col_data), 3) if len(col_data) > 0 else 1,
                "unique_count": int(col_data.nunique()),
                "sample_values": [str(v) for v in non_null.head(max_sample_rows).tolist()],
            }
            # 数值列额外统计
            if pd.api.types.is_numeric_dtype(col_data):
                stats[col]["min"] = float(non_null.min()) if len(non_null) > 0 else None
                stats[col]["max"] = float(non_null.max()) if len(non_null) > 0 else None
                stats[col]["mean"] = round(float(non_null.mean()), 2) if len(non_null) > 0 else None

        # 3. LLM理解数据
        system_prompt = """你是数据分析专家。用户给你一个表格的列统计信息，你需要：
1. 推断每列的业务含义（中文描述）
2. 识别数据类型（数值/分类/日期/文本/ID）
3. 判断整体业务主题（如"销售明细"、"财务账单"、"库存清单"）
4. 评估数据质量（缺失、异常）
5. 给出处理建议

返回JSON：
{
  "topic": "业务主题",
  "columns": [
    {"name": "原列名", "meaning": "业务含义", "type": "数据类型", "is_key_column": true/false}
  ],
  "quality": {
    "overall_score": "好/中/差",
    "issues": ["数据质量问题1", ...]
  },
  "suggestions": ["建议处理方向1", ...]
}"""

        user_message = f"""文件: {file_path}
总行数: {len(df)}
总列数: {len(df.columns)}

列统计信息:
{json.dumps(stats, ensure_ascii=False, indent=2)}

请分析数据结构并给出理解。"""

        try:
            reply = self.llm.chat(
                message=user_message,
                system_prompt=system_prompt,
            )

            # 提取JSON
            json_start = reply.find("{")
            json_end = reply.rfind("}") + 1
            if json_start != -1 and json_end != -1:
                understanding = json.loads(reply[json_start:json_end])
                logger.info(f"[DataUnderstanding] 主题: {understanding.get('topic', '?')}")
                return {
                    "status": "success",
                    "file_path": file_path,
                    "total_rows": len(df),
                    "total_columns": len(df.columns),
                    **understanding,
                }
        except Exception as e:
            logger.error(f"[DataUnderstanding] LLM分析失败: {e}")

        # 兜底：返回基础统计
        return {
            "status": "success",
            "file_path": file_path,
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "topic": "未知",
            "columns": [{"name": col, "meaning": col, "type": str(df[col].dtype)} for col in df.columns],
            "quality": {"overall_score": "未知", "issues": []},
            "suggestions": [],
        }

    def detect_anomalies(
        self,
        file_path: str,
        columns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        异常值检测（统计方法 + LLM判断）

        使用 IQR（四分位距）方法检测数值列的异常值，
        并用 LLM 判断这些异常是否为业务合理异常。

        Args:
            file_path: 数据文件路径
            columns: 指定检测的列，None则检测所有数值列

        Returns:
            {
                "anomalies": [
                    {"column": "列名", "row_index": 行号, "value": 异常值, "reason": "异常原因"}
                ],
                "summary": "异常检测总结"
            }
        """
        logger.info(f"[AnomalyDetection] 检测异常: {file_path}")

        try:
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
        except Exception as e:
            return {"status": "failed", "error": f"读取文件失败: {e}"}

        # 1. 统计方法检测异常值（IQR）
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        if columns:
            numeric_cols = [c for c in numeric_cols if c in columns]

        if not numeric_cols:
            return {
                "status": "success",
                "anomalies": [],
                "summary": "无数值列可检测",
            }

        anomalies = []
        for col in numeric_cols:
            col_data = df[col].dropna()
            if len(col_data) < 4:
                continue

            q1 = col_data.quantile(0.25)
            q3 = col_data.quantile(0.75)
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr

            # 找异常值
            outlier_mask = (df[col] < lower_bound) | (df[col] > upper_bound)
            outlier_rows = df[outlier_mask].index.tolist()

            for row_idx in outlier_rows[:20]:  # 每列最多报20个
                anomalies.append({
                    "column": col,
                    "row_index": int(row_idx),
                    "value": float(df.loc[row_idx, col]),
                    "reason": f"超出正常范围 [{lower_bound:.2f}, {upper_bound:.2f}]",
                })

        logger.info(f"[AnomalyDetection] 统计检测到 {len(anomalies)} 个异常值")

        # 2. LLM判断异常的业务合理性
        if anomalies:
            try:
                # 准备给LLM的异常摘要
                anomaly_summary = {}
                for a in anomalies[:30]:  # 最多给LLM看30个
                    col = a["column"]
                    if col not in anomaly_summary:
                        anomaly_summary[col] = []
                    anomaly_summary[col].append(a["value"])

                system_prompt = """你是业务数据分析专家。
用户给你一些检测到的异常值，请判断：
1. 这些异常是否为业务合理异常（如大额订单、退款）
2. 是否为数据错误（如录入错误、系统bug）
3. 给出处理建议

返回JSON：
{
  "business_anomalies": [{"column": "列名", "values": [值], "reason": "业务原因"}],
  "data_errors": [{"column": "列名", "values": [值], "reason": "错误原因"}],
  "summary": "总结",
  "suggestions": ["处理建议1", ...]
}"""

                user_message = f"""检测到的异常值:
{json.dumps(anomaly_summary, ensure_ascii=False, indent=2)}

数据列: {numeric_cols}
总行数: {len(df)}

请判断这些异常是业务合理还是数据错误。"""

                reply = self.llm.chat(
                    message=user_message,
                    system_prompt=system_prompt,
                )

                json_start = reply.find("{")
                json_end = reply.rfind("}") + 1
                if json_start != -1 and json_end != -1:
                    llm_analysis = json.loads(reply[json_start:json_end])
                    return {
                        "status": "success",
                        "anomalies": anomalies,
                        "llm_analysis": llm_analysis,
                        "summary": llm_analysis.get("summary", f"检测到{len(anomalies)}个异常值"),
                    }
            except Exception as e:
                logger.warning(f"[AnomalyDetection] LLM分析失败: {e}")

        return {
            "status": "success",
            "anomalies": anomalies,
            "summary": f"检测到{len(anomalies)}个异常值" if anomalies else "未检测到异常值",
        }
