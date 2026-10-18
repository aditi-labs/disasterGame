# Physical Piece Reference Images

Reference photos for Perceptron classification.

## YOUR ACTUAL TOKENS (Verified by viewing photos)

| Piece | Color | Shape | File |
|-------|-------|-------|------|
| Bridge | **YELLOW** | Elongated with railings | `bridge.jpg` |
| Hospital | **PINK** cross on **WHITE** | Medical cross symbol | `hospital.jpg` |
| Food Station | **WHITE** base with **BLUE** circles | Supply depot | `food_station.jpg` |
| Shelter | White | House with roof | `shelter.jpg` (if available) |

## Status

- `bridge.jpg` - UPLOADED, VERIFIED, WORKING
- `hospital.jpg` - UPLOADED, VERIFIED, WORKING
- `food_station.jpg` - UPLOADED, VERIFIED, WORKING

**Accuracy: 3/3 (100%)**

## How Detection Works

The Perceptron API uses your reference photos' visual features:
- **Yellow** elongated piece with railings = Bridge
- **Pink/magenta** cross on white base = Hospital
- **White** base with **blue** circles = Food Station
- Pure **white** house shape = Shelter
