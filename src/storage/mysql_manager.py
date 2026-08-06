# -*- coding: utf-8 -*-
"""
MySQL管理器

功能：
1. 业务数据存储 - 下载的报表数据、处理结果
2. 任务执行历史 - 记录每次任务执行的情况
3. 通用CRUD - 提供简洁的数据操作接口

设计要点：
- 懒加载：第一次调用时才连接
- 连接池：SQLAlchemy连接池，复用连接
- 自动建表：首次使用自动创建所需表
- 异步兼容：提供同步接口，不阻塞主流程
"""
import json
import time
from typing import Any, Optional, List, Dict
from datetime import datetime
from loguru import logger

try:
    from sqlalchemy import create_engine, text, Column, Integer, String, Text, DateTime, JSON
    from sqlalchemy.orm import sessionmaker, declarative_base
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    logger.warning("未安装sqlalchemy库，MySQL功能不可用。安装: pip install sqlalchemy pymysql")

if HAS_SQLALCHEMY:
    Base = declarative_base()


class MySQLManager:
    """MySQL管理器"""

    def __init__(self, host: str = 'localhost', port: int = 3306,
                 user: str = 'root', password: str = '', database: str = 'smart_agent',
                 charset: str = 'utf8mb4'):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.charset = charset
        self._engine = None
        self._session_factory = None

    @property
    def engine(self):
        """懒加载SQLAlchemy引擎"""
        if not HAS_SQLALCHEMY:
            return None
        if self._engine is None:
            try:
                url = f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}?charset={self.charset}"
                self._engine = create_engine(
                    url,
                    pool_size=5,
                    max_overflow=10,
                    pool_recycle=3600,
                    echo=False,
                )
                # 测试连接
                with self._engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                logger.info(f"MySQL连接成功: {self.host}:{self.port}/{self.database}")

                # 自动建库（如果不存在）
                self._ensure_database()
                # 自动建表
                self._create_tables()

            except Exception as e:
                logger.warning(f"MySQL连接失败: {e}")
                # 尝试创建数据库
                if "Unknown database" in str(e):
                    self._create_database()
                else:
                    self._engine = None
                return None
        return self._engine

    def _create_database(self):
        """创建数据库"""
        try:
            url = f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/?charset={self.charset}"
            engine = create_engine(url)
            with engine.connect() as conn:
                conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {self.database} CHARACTER SET {self.charset}"))
                conn.commit()
            engine.dispose()
            logger.info(f"数据库已创建: {self.database}")
            # 重新连接
            self._engine = None
            _ = self.engine
        except Exception as e:
            logger.error(f"创建数据库失败: {e}")

    def _ensure_database(self):
        pass  # engine已连接到指定库，无需额外操作

    def _create_tables(self):
        """自动创建所需的表"""
        if not HAS_SQLALCHEMY or self._engine is None:
            return

        from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, MetaData

        metadata = MetaData()

        # 1. 任务执行历史表
        from sqlalchemy import Table
        Table('task_history', metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('task_id', String(100), index=True),
            Column('task_name', String(200)),
            Column('status', String(20), index=True),  # success/failed
            Column('start_time', DateTime),
            Column('end_time', DateTime),
            Column('elapsed_time', String(50)),
            Column('steps_total', Integer, default=0),
            Column('steps_completed', Integer, default=0),
            Column('error_message', Text),
            Column('context', Text),  # JSON格式的执行上下文
            Column('created_at', DateTime, default=datetime.now),
        )

        # 2. 下载记录表
        Table('download_records', metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('task_id', String(100), index=True),
            Column('task_name', String(200)),
            Column('file_name', String(500)),
            Column('file_path', String(1000)),
            Column('file_size', Integer, default=0),
            Column('source_url', String(1000)),
            Column('download_time', DateTime, default=datetime.now),
        )

        # 3. 业务数据表（通用，存储处理结果）
        Table('business_data', metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('task_id', String(100), index=True),
            Column('task_name', String(200)),
            Column('data_type', String(100), index=True),  # 数据类型：sales/refund/stock等
            Column('data_key', String(200)),                # 数据键：如"2026-07月销售额"
            Column('data_value', Text),                      # 数据值
            Column('raw_data', Text),                        # 原始数据（JSON）
            Column('remark', String(500)),
            Column('created_at', DateTime, default=datetime.now),
        )

        try:
            metadata.create_all(self._engine)
            logger.info("MySQL表已就绪")
        except Exception as e:
            logger.warning(f"建表失败: {e}")

    def get_session(self):
        """获取数据库会话"""
        if self._session_factory is None:
            if self.engine is None:
                return None
            self._session_factory = sessionmaker(bind=self._engine)
        return self._session_factory()

    # ==================== 任务历史 ====================

    def save_task_history(self, task_id: str, task_name: str, status: str,
                          start_time: str = None, end_time: str = None,
                          elapsed_time: str = None, steps_total: int = 0,
                          steps_completed: int = 0, error_message: str = None,
                          context: dict = None) -> bool:
        """保存任务执行历史"""
        if not HAS_SQLALCHEMY or self.engine is None:
            return False
        try:
            with self.engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO task_history
                    (task_id, task_name, status, start_time, end_time,
                     elapsed_time, steps_total, steps_completed,
                     error_message, context, created_at)
                    VALUES
                    (:task_id, :task_name, :status, :start_time, :end_time,
                     :elapsed_time, :steps_total, :steps_completed,
                     :error_message, :context, :created_at)
                """), {
                    'task_id': task_id,
                    'task_name': task_name,
                    'status': status,
                    'start_time': start_time,
                    'end_time': end_time,
                    'elapsed_time': elapsed_time,
                    'steps_total': steps_total,
                    'steps_completed': steps_completed,
                    'error_message': error_message,
                    'context': json.dumps(context, ensure_ascii=False) if context else None,
                    'created_at': datetime.now(),
                })
                conn.commit()
            logger.info(f"任务历史已保存: {task_id} - {status}")
            return True
        except Exception as e:
            logger.error(f"保存任务历史失败: {e}")
            return False

    def query_task_history(self, task_id: str = None, status: str = None,
                           limit: int = 50) -> List[Dict]:
        """查询任务执行历史"""
        if not HAS_SQLALCHEMY or self.engine is None:
            return []
        try:
            sql = "SELECT * FROM task_history WHERE 1=1"
            params = {}
            if task_id:
                sql += " AND task_id = :task_id"
                params['task_id'] = task_id
            if status:
                sql += " AND status = :status"
                params['status'] = status
            sql += " ORDER BY created_at DESC LIMIT :limit"
            params['limit'] = limit

            with self.engine.connect() as conn:
                result = conn.execute(text(sql), params)
                rows = result.fetchall()
                columns = result.keys()

            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"查询任务历史失败: {e}")
            return []

    # ==================== 下载记录 ====================

    def save_download_record(self, task_id: str, task_name: str,
                             file_name: str, file_path: str,
                             file_size: int = 0, source_url: str = '') -> bool:
        """保存下载记录"""
        if not HAS_SQLALCHEMY or self.engine is None:
            return False
        try:
            with self.engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO download_records
                    (task_id, task_name, file_name, file_path,
                     file_size, source_url, download_time)
                    VALUES
                    (:task_id, :task_name, :file_name, :file_path,
                     :file_size, :source_url, :download_time)
                """), {
                    'task_id': task_id,
                    'task_name': task_name,
                    'file_name': file_name,
                    'file_path': file_path,
                    'file_size': file_size,
                    'source_url': source_url,
                    'download_time': datetime.now(),
                })
                conn.commit()
            logger.info(f"下载记录已保存: {file_name}")
            return True
        except Exception as e:
            logger.error(f"保存下载记录失败: {e}")
            return False

    # ==================== 业务数据 ====================

    def save_business_data(self, task_id: str, task_name: str,
                           data_type: str, data_key: str, data_value: str,
                           raw_data: dict = None, remark: str = '') -> bool:
        """
        保存业务数据

        Args:
            task_id: 任务ID
            task_name: 任务名称
            data_type: 数据类型（sales/refund/stock等）
            data_key: 数据键（如"2026-07月销售额"）
            data_value: 数据值
            raw_data: 原始数据（JSON）
            remark: 备注
        """
        if not HAS_SQLALCHEMY or self.engine is None:
            return False
        try:
            with self.engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO business_data
                    (task_id, task_name, data_type, data_key,
                     data_value, raw_data, remark, created_at)
                    VALUES
                    (:task_id, :task_name, :data_type, :data_key,
                     :data_value, :raw_data, :remark, :created_at)
                """), {
                    'task_id': task_id,
                    'task_name': task_name,
                    'data_type': data_type,
                    'data_key': data_key,
                    'data_value': data_value,
                    'raw_data': json.dumps(raw_data, ensure_ascii=False) if raw_data else None,
                    'remark': remark,
                    'created_at': datetime.now(),
                })
                conn.commit()
            logger.info(f"业务数据已保存: {data_type}/{data_key}")
            return True
        except Exception as e:
            logger.error(f"保存业务数据失败: {e}")
            return False

    def query_business_data(self, data_type: str = None, task_id: str = None,
                            limit: int = 100) -> List[Dict]:
        """查询业务数据"""
        if not HAS_SQLALCHEMY or self.engine is None:
            return []
        try:
            sql = "SELECT * FROM business_data WHERE 1=1"
            params = {}
            if data_type:
                sql += " AND data_type = :data_type"
                params['data_type'] = data_type
            if task_id:
                sql += " AND task_id = :task_id"
                params['task_id'] = task_id
            sql += " ORDER BY created_at DESC LIMIT :limit"
            params['limit'] = limit

            with self.engine.connect() as conn:
                result = conn.execute(text(sql), params)
                rows = result.fetchall()
                columns = result.keys()

            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"查询业务数据失败: {e}")
            return []

    # ==================== 通用SQL执行 ====================

    def execute_sql(self, sql: str, params: dict = None) -> Optional[List[Dict]]:
        """
        执行任意SQL语句（查询返回结果，更新返回None）

        Args:
            sql: SQL语句（使用命名参数 :param）
            params: 参数字典

        Returns:
            查询返回结果列表，非查询返回None
        """
        if not HAS_SQLALCHEMY or self.engine is None:
            return None
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql), params or {})
                # 判断是否是查询
                if result.returns_rows:
                    rows = result.fetchall()
                    columns = result.keys()
                    conn.commit()
                    return [dict(zip(columns, row)) for row in rows]
                else:
                    conn.commit()
                    return None
        except Exception as e:
            logger.error(f"SQL执行失败: {e}")
            return None

    def close(self):
        """关闭连接"""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            logger.info("MySQL连接已关闭")


    # ==================== 动态建表 ====================

    def create_business_table(self, table_name: str, columns: List[Dict]) -> bool:
        """
        动态创建业务数据表

        Args:
            table_name: 表名（会自动加前缀 smart_agent_）
            columns: 列定义列表 [{name, type, comment}]
                示例: [
                    {"name": "id", "type": "INT AUTO_INCREMENT PRIMARY KEY"},
                    {"name": "task_id", "type": "VARCHAR(100)", "comment": "任务ID"},
                    {"name": "sales_amount", "type": "DECIMAL(15,2)", "comment": "销售额"},
                ]
        """
        if not HAS_SQLALCHEMY or self.engine is None:
            return False
        try:
            full_table = f"smart_agent_{table_name}"
            cols_sql = ", ".join([
                f"`{c['name']}` {c['type']}" + (f" COMMENT '{c.get('comment', '')}'" if c.get('comment') else '')
                for c in columns
            ])
            sql = f"""
            CREATE TABLE IF NOT EXISTS `{full_table}` (
                {cols_sql},
                `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX `idx_task_id` (`task_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='智能体业务数据表-{table_name}'
            """
            with self.engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
            logger.info(f"业务数据表已创建: {full_table}")
            return True
        except Exception as e:
            logger.error(f"建表失败: {e}")
            return False

    def list_business_tables(self) -> List[str]:
        """列出所有业务数据表"""
        if not HAS_SQLALCHEMY or self.engine is None:
            return []
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT TABLE_NAME, TABLE_COMMENT, TABLE_ROWS 
                    FROM information_schema.TABLES 
                    WHERE TABLE_SCHEMA = DATABASE() 
                    AND TABLE_NAME LIKE 'smart_agent_%'
                """))
                rows = result.fetchall()
                columns = result.keys()
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"查询业务表失败: {e}")
            return []

    def drop_business_table(self, table_name: str) -> bool:
        """删除业务数据表"""
        if not HAS_SQLALCHEMY or self.engine is None:
            return False
        try:
            full_table = f"smart_agent_{table_name}"
            with self.engine.connect() as conn:
                conn.execute(text(f"DROP TABLE IF EXISTS `{full_table}`"))
                conn.commit()
            logger.info(f"业务数据表已删除: {full_table}")
            return True
        except Exception as e:
            logger.error(f"删表失败: {e}")
            return False

    def query_business_table(self, table_name: str, conditions: dict = None, 
                              limit: int = 100, offset: int = 0) -> List[Dict]:
        """查询业务数据表"""
        if not HAS_SQLALCHEMY or self.engine is None:
            return []
        try:
            full_table = f"smart_agent_{table_name}"
            sql = f"SELECT * FROM `{full_table}` WHERE 1=1"
            params = {}
            if conditions:
                for key, value in conditions.items():
                    sql += f" AND `{key}` = :{key}"
                    params[key] = value
            sql += " ORDER BY `id` DESC LIMIT :limit OFFSET :offset"
            params['limit'] = limit
            params['offset'] = offset

            with self.engine.connect() as conn:
                result = conn.execute(text(sql), params)
                rows = result.fetchall()
                columns = result.keys()
                return [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            logger.error(f"查询业务表失败: {e}")
            return []

    def insert_business_row(self, table_name: str, data: dict) -> bool:
        """向业务数据表插入一行"""
        if not HAS_SQLALCHEMY or self.engine is None:
            return False
        try:
            full_table = f"smart_agent_{table_name}"
            columns = ", ".join([f"`{k}`" for k in data.keys()])
            values = ", ".join([f":{k}" for k in data.keys()])
            sql = f"INSERT INTO `{full_table}` ({columns}) VALUES ({values})"
            with self.engine.connect() as conn:
                conn.execute(text(sql), data)
                conn.commit()
            logger.info(f"数据已插入 {full_table}")
            return True
        except Exception as e:
            logger.error(f"插入数据失败: {e}")
            return False
