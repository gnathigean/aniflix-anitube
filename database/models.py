from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database.db import Base

class Anime(Base):
    __tablename__ = "animes"
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String, index=True)
    url_capa = Column(String)
    sinopse = Column(String, default="")
    formato = Column(String, default="")
    genero = Column(String, default="")
    autor = Column(String, default="")
    estudio = Column(String, default="")
    ano = Column(String, default="")
    status = Column(String, default="")
    qtd_dub = Column(Integer, default=0)
    qtd_leg = Column(Integer, default=0)
    visualizacoes_total = Column(Integer, default=0)
    temporadas = relationship("Temporada", back_populates="anime", cascade="all, delete-orphan", order_by="Temporada.numero")
    favoritos = relationship("Favorito", back_populates="anime", cascade="all, delete-orphan")

class Temporada(Base):
    __tablename__ = "temporadas"
    id = Column(Integer, primary_key=True, index=True)
    anime_id = Column(Integer, ForeignKey("animes.id"))
    numero = Column(Integer, nullable=False, default=1)
    titulo_temporada = Column(String, nullable=True)
    anime = relationship("Anime", back_populates="temporadas")
    episodios = relationship("Episodio", back_populates="temporada", cascade="all, delete-orphan", order_by="Episodio.numero")

class Episodio(Base):
    __tablename__ = "episodios"
    id = Column(Integer, primary_key=True, index=True)
    temporada_id = Column(Integer, ForeignKey("temporadas.id"))
    numero = Column(Integer, nullable=False)
    titulo_episodio = Column(String, nullable=True)
    tipo = Column(String, nullable=True)
    url_episodio_origem = Column(String, nullable=True)  # URL da página de origem (para extração on-demand)
    url_stream_original = Column(String, nullable=True)
    headers_b64 = Column(String, nullable=True)
    idioma = Column(String, nullable=True, default="Legendado")
    views_total = Column(Integer, default=0)
    views_dia = Column(Integer, default=0)
    views_semana = Column(Integer, default=0)
    views_mes = Column(Integer, default=0)
    temporada = relationship("Temporada", back_populates="episodios")
    progressos = relationship("Progresso", back_populates="episodio", cascade="all, delete-orphan")

class Favorito(Base):
    __tablename__ = "favoritos"
    id = Column(Integer, primary_key=True, index=True)
    anime_id = Column(Integer, ForeignKey("animes.id"))
    session_id = Column(String, nullable=False, index=True)
    criado_em = Column(DateTime, server_default=func.now())
    anime = relationship("Anime", back_populates="favoritos")

class Progresso(Base):
    __tablename__ = "progressos"
    id = Column(Integer, primary_key=True, index=True)
    episodio_id = Column(Integer, ForeignKey("episodios.id"))
    session_id = Column(String, nullable=False, index=True)
    progresso_segundos = Column(Float, default=0)
    duracao_segundos = Column(Float, default=0)
    atualizado_em = Column(DateTime, server_default=func.now(), onupdate=func.now())
    episodio = relationship("Episodio", back_populates="progressos")