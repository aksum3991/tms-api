from core.signature_model import compare_signatures_with_model


if __name__ == "__main__":
    path1 = "sign1.jpg" #eplace with your first signature image path
    path2 = "sign2.jpg" #eplace with your second signature image path
    import time
    start = time.time()
    similarity = compare_signatures_with_model(path1, path2)
    end = time.time()
    print(f"Similarity score: {similarity:.4f}")

    # Interpret result
    if similarity > 0.35:
        print("Signatures are similar (above threshold).")
    else:
        print("Signatures are different (below threshold).")
    print(f"Runtime: {end - start:.2f} seconds")