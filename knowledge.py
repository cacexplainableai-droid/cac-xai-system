"""Knowledge assistant: searches ONLY the approved documents stored in the database.
It never writes its own answers: it returns the matching passages and names the source document."""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
import config


def search(conn, query, top_k=3):
    docs = conn.execute("SELECT id, title, category, content FROM documents").fetchall()
    chunks = []
    for d in docs:
        for para in d["content"].split("\n\n"):
            para = para.strip()
            if len(para) > 30:
                chunks.append(dict(title=d["title"], category=d["category"], passage=para))
    if not query.strip() or not chunks:
        return []
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
    mat = vec.fit_transform([c["title"] + " " + c["passage"] for c in chunks])
    scores = linear_kernel(vec.transform([query]), mat).ravel()
    order = scores.argsort()[::-1][:top_k]
    return [dict(chunks[i], score=float(scores[i])) for i in order if scores[i] >= config.ASSISTANT_MIN_SCORE]
