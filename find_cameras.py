import cv2

print("Scanning for cameras...")
for i in range(10):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    if cap.isOpened():
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        name = cap.getBackendName()
        print(f"  Index {i}: FOUND - {w}x{h} ({name})")
        cap.release()
    else:
        print(f"  Index {i}: not available")

print("\nTrying MSMF backend...")
for i in range(10):
    cap = cv2.VideoCapture(i, cv2.CAP_MSMF)
    if cap.isOpened():
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"  Index {i}: FOUND - {w}x{h} (MSMF)")
        cap.release()
