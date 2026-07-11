"""
Memoria de largo plazo: conocimiento persistente indexado por embeddings.

Guarda: patrones error->reparación exitosos, "recetas" de herramientas
creadas, decisiones/preferencias relevantes, y referencias a artefactos
multimedia (imagen/audio/video) — el binario vive en almacenamiento de
objetos (ver tool_integration/), aquí solo se indexa su descripción.

Embeddings: modelo local vía sentence-transformers (por defecto
all-MiniLM-L6-v2, ~80MB). Se descarga una única vez desde HuggingFace
Hub la primera vez que se instancia esta clase; después queda cacheado
en disco (~/.cache/huggingface) y no vuelve a requerir red. Esta
decisión es deliberada: mantiene la memoria de largo plazo funcionando
sin depender de una API externa ni exponer contenido potencialmente
sensible (ver TODO de sanitización abajo) a un tercero solo para
generar el embedding.

Backend vectorial: Chroma, en uno de dos modos (ver config.yaml,
memory.long_term.mode):
  - embedded: corre dentro del propio proceso, persistido en disco
    local. Sin red, sin servicio aparte. Es el default.
  - http: usa el servicio `vector_store` de docker-compose vía red
    interna. Útil si varios procesos/workers necesitan compartir índice.

Nada entra aquí automáticamente: solo lo que pasó la política de
promoción evaluada en agent_core/orchestrator.py sobre los candidatos
que expone MidTermMemory.candidates_for_promotion().
"""
from __future__ import annotations

from pathlib import Path

from agent_core.memory.base import MemoryBackend, MemoryConfidence, MemoryItem
from utils.config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

COLLECTION_NAME = "kal_long_term_memory"


class LongTermMemory(MemoryBackend):
    def __init__(self):
        self.cfg = settings.memory.long_term
        self._embedder = None  # carga perezosa, ver _get_embedder()
        self.client = self._build_client()
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def _build_client(self):
        import chromadb

        if self.cfg.mode == "http":
            return chromadb.HttpClient(host=self.cfg.http_host, port=self.cfg.http_port)

        persist_path = Path(self.cfg.persist_path)
        persist_path.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=str(persist_path))

    def _get_embedder(self):
        """
        Carga perezosa del modelo de embeddings: evita pagar el costo
        de carga (y la posible descarga inicial) si LongTermMemory se
        instancia pero nunca se usa en un proceso dado.
        """
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Cargando modelo de embeddings: {self.cfg.embedding_model}")
            self._embedder = SentenceTransformer(self.cfg.embedding_model)
        return self._embedder

    def _embed(self, text: str) -> list[float]:
        embedder = self._get_embedder()
        vector = embedder.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return vector.tolist()

    def store(self, item: MemoryItem) -> None:
        embedding = self._embed(item.content)
        # Chroma exige metadata con valores planos (str/int/float/bool),
        # sin dicts anidados ni None — se serializa lo que no cumpla.
        flat_metadata = self._flatten_metadata(item.metadata)
        flat_metadata["repetitions"] = item.repetitions
        flat_metadata["relevance_score"] = item.relevance_score
        flat_metadata["created_at"] = item.created_at
        flat_metadata["confidence"] = item.confidence.value

        self.collection.upsert(
            ids=[item.id],
            embeddings=[embedding],
            documents=[item.content],
            metadatas=[flat_metadata],
        )

    def retrieve(self, query: str, top_k: int = 5) -> list[MemoryItem]:
        if self.collection.count() == 0:
            return []
        query_embedding = self._embed(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.collection.count()),
        )
        ids = results["ids"][0]
        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        return [
            self._to_item(item_id, content, metadata)
            for item_id, content, metadata in zip(ids, documents, metadatas)
        ]

    def get_by_id(self, item_id: str) -> MemoryItem | None:
        """
        Lookup exacto por id (sin búsqueda semántica), necesario para
        MemoryManager.verify()/pin() sobre un item ya promovido a largo
        plazo — subir su confianza requiere poder recuperarlo por clave,
        no por similitud de contenido.
        """
        result = self.collection.get(ids=[item_id])
        ids = result.get("ids") or []
        if not ids:
            return None
        return self._to_item(ids[0], result["documents"][0], result["metadatas"][0])

    def forget(self, item_id: str) -> None:
        self.collection.delete(ids=[item_id])

    @staticmethod
    def _to_item(item_id: str, content: str, metadata: dict) -> MemoryItem:
        metadata = dict(metadata)
        return MemoryItem(
            id=item_id,
            content=content,
            metadata=metadata,
            created_at=metadata.get("created_at", 0.0),
            relevance_score=metadata.get("relevance_score", 0.0),
            repetitions=metadata.get("repetitions", 1),
            confidence=MemoryConfidence(metadata.get("confidence", "temporal")),
        )

    def store_artifact_reference(
        self, description: str, artifact_uri: str, modality: str, metadata: dict
    ) -> None:
        """
        Indexa un artefacto multimedia (imagen/audio/video) por la
        descripción/prompt que lo generó, no por su binario. El binario
        vive en el almacenamiento de objetos referenciado en artifact_uri
        (ver tool_integration/adapters/).
        """
        item = MemoryItem(
            content=description,
            metadata={**metadata, "artifact_uri": artifact_uri, "modality": modality},
        )
        self.store(item)

    @staticmethod
    def _flatten_metadata(metadata: dict) -> dict:
        """
        Chroma no acepta None ni estructuras anidadas como valores de
        metadata. Convierte lo que no sea str/int/float/bool a string
        (json.dumps) y descarta claves con valor None.

        TODO(seguridad): este es también el punto donde debería vivir
        la sanitización de contenido sensible antes de persistir a largo
        plazo (credenciales, PII) — ver nota en README sobre qué se
        considera "sensible" en memoria. Pendiente de definir la
        política exacta antes de usar esto en producción con datos
        reales de usuario.
        """
        import json

        flat = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                flat[key] = value
            else:
                flat[key] = json.dumps(value)
        return flat
