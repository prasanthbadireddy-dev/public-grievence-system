import sys
sys.path.append('.')
from app import find_duplicates, tfidf_vectorize, cosine_similarity

t1 = "The water supply is not consistent"
t2 = "We are not reciveing water every day"
v1, v2 = tfidf_vectorize([t1, t2])
sim = cosine_similarity(v1, v2)
print("Cosine Sim:", sim)
