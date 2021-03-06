#!/usr/bin/env python
__author__ = 'Calvin'

import os, time, glob
from os.path import join
import cv2
import numpy as np
from numpy.linalg import norm
from multiprocessing.pool import ThreadPool
import yaml, re

def get_images(path):
    ls = []
    if os.path.isdir(path) and os.listdir(path):
        ls = os.listdir(path)
    else:
        print 'No images found at %s' % path
    return ls and map(lambda x: join(path, x), ls)


def get_mat(image, size=None):
    im = cv2.imread(image, 0)
    if size:
        im = cv2.resize(im, size, interpolation=cv2.INTER_CUBIC)
    return im


def timer(func):
    def newFunc(*args, **args2):
        start = time.time()
        back = func(*args, **args2)
        print "Timer: %.4fs" % (time.time()-start)
        return back
    return newFunc


def multi_thread(f, jobs):
    pool = ThreadPool(processes=cv2.getNumberOfCPUs())
    ires = pool.imap_unordered(f, jobs)
    return ires


def resize_scale(src_dir, dst_dir, size, fmt, name, start=1):
    if os.path.isdir(src_dir) and os.path.isdir(dst_dir) and size and fmt and name:
        src = glob.glob(join(src_dir, r'*.'+fmt))
        no = start
        for img in src:
            im = cv2.imread(img)
            rs = cv2.resize(im, size, interpolation=cv2.INTER_LINEAR)
            fm = '%s\%s_%04d.%s' % (dst_dir, name, no, fmt)
            no += 1
            cv2.imwrite(fm, rs)


def cut_image(src, dst, x, y, (w, h)):
    im = cv2.imread(src)
    if im.shape[0]<w+x or im.shape[1]<h+y:
        r = max(float(w+x)/im.shape[0], float(h+y)/im.shape[1])
        im = cv2.resize(im, (int(im.shape[0]*r+0.5), int(im.shape[1]*r+0.5)), interpolation=cv2.INTER_AREA)
    rs = im[x:w+x, y:h+y]
    cv2.imwrite(dst,rs)


class RectSelector:
    def __init__(self, win, callback, scale=None):
        self.win = win
        self.callback = callback
        cv2.setMouseCallback(win, self.on_mouse)
        self.drag_start = None
        self.drag_rect = None
        self.scale = scale
    def on_mouse(self, event, x, y, flags, param):
        x, y = np.int16([x, y]) # BUG
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drag_start = (x, y)
        if self.drag_start:
            if flags & cv2.EVENT_FLAG_LBUTTON:
                xo, yo = self.drag_start
                x0, y0 = np.minimum([xo, yo], [x, y])
                if isinstance(self.scale, tuple):
                    y = (x-xo)*self.scale[1]/self.scale[0] + yo
                x1, y1 = np.maximum([xo, yo], [x, y])
                self.drag_rect = None
                if x1-x0 > 0 and y1-y0 > 0:
                    self.drag_rect = (x0, y0, x1, y1)
            else:
                rect = self.drag_rect
                self.drag_start = None
                self.drag_rect = None
                if rect:
                    self.callback(rect)
    def draw(self, vis):
        if not self.drag_rect:
            return False
        x0, y0, x1, y1 = self.drag_rect
        cv2.rectangle(vis, (x0, y0), (x1, y1), (0, 255, 0), 2)
        return True
    @property
    def dragging(self):
        return self.drag_rect is not None


class StatModel(object):
    """parent class - starting point to add abstraction"""
    def load(self, fn):
        if os.path.isfile(fn):
            print 'loading "%s" ...' % fn
            self.model.load(fn)
            print '"%s" loaded successfully' % fn
        else:
            print '"%s" loading failed' % fn
            exit()
    def save(self, fn):
        try:
            self.model.save(fn)
            print '"%s" saved successfully' % fn
        except Exception:
            print '"%s" saving failed' % fn


class Feature(object):
    def process(self): pass


class SVM(StatModel):
    """wrapper for OpenCV SVM algorithm"""
    def __init__(self, **params):
        self.model = cv2.SVM()
        self.params = params
    def train(self, samples, responses):
        """setting algorithm parameters
        params = dict( kernel_type = cv2.SVM_RBF,
                       svm_type = cv2.SVM_C_SVC,
                       C = 1
        )"""
        #print map((lambda (key, val): '%s: %s' % (key, val)), self.params.items())
        timer = time.time()
        self.model.train(samples, responses, params=self.params)
        self.timer = time.time() - timer
    def predict(self, samples):
        return self.model.predict_all(samples).ravel()
        #return np.float32([self.model.predict(s) for s in samples])


class HOG(Feature):
    """_winSize, _blockSize, _blockStride, _cellSize, _nbins
    cv2.HOGDescriptor((128,64), (16,16), (8,8), (8,8), 9)
    hog_num: ((64-16)/8+1)*((128-16)/8+1)*9*4"""
    def __init__(self, **params):
        self.default_params = dict(
            #_winSize = (64,128),
            _blockSize = (16,16),
            _blockStride = (8,8),
            _cellSize = (8,8),
            _nbins = 9,
            _derivAperture = 1,
            _winSigma = -1,
            _histogramNormType = cv2.HOGDESCRIPTOR_L2HYS,
            _L2HysThreshold = 0.2,
            _gammaCorrection = False,
            _nlevels = cv2.HOGDESCRIPTOR_DEFAULT_NLEVELS
        )
        params.update(self.default_params)
        self.hog = cv2.HOGDescriptor(**params)
        self.winSize = params.get('_winSize')
        assert self.winSize, '_winSize is required'
        self.num = ((params['_winSize'][0]-params['_blockSize'][0])/params['_blockStride'][0]+1)* \
                   ((params['_winSize'][1]-params['_blockSize'][1])/params['_blockStride'][1]+1)* \
                   params['_blockSize'][0]*params['_blockSize'][1]/(params['_cellSize'][0]*params['_cellSize'][1])*params['_nbins']
    def process(self, samples, size=None):
        res = []
        if isinstance(samples[0], str):
            for img in samples:
                im = cv2.imread(img, 0)
                rs = self.hog.compute(im)
                res.append(rs.ravel())
        else:
            for im in samples:
                rs = self.hog.compute(im)
                res.append(rs.ravel())
        return np.float32(res)


def preprocess(pos, neg, feature):
    samples = feature.process(pos+neg)
    labels = np.append(np.ones(len(pos), np.int32), np.zeros(len(neg), np.int32))
    shuffle = np.random.permutation(len(samples))
    return samples[shuffle], labels[shuffle]
    # return samples, labels


def preprocess_hog(digits):
    samples = []
    for img in digits:
        gx = cv2.Sobel(img, cv2.CV_32F, 1, 0)
        gy = cv2.Sobel(img, cv2.CV_32F, 0, 1)
        mag, ang = cv2.cartToPolar(gx, gy)
        bin_n = 16
        bin = np.int32(bin_n*ang/(2*np.pi))
        bin_cells = bin[:10,:10], bin[10:,:10], bin[:10,10:], bin[10:,10:]
        mag_cells = mag[:10,:10], mag[10:,:10], mag[:10,10:], mag[10:,10:]
        hists = [np.bincount(b.ravel(), m.ravel(), bin_n) for b, m in zip(bin_cells, mag_cells)]
        hist = np.hstack(hists)

        # transform to Hellinger kernel
        eps = 1e-7
        hist /= hist.sum() + eps
        hist = np.sqrt(hist)
        hist /= norm(hist) + eps

        samples.append(hist)
    return np.float32(samples)


def cross_validate(model_class, params, samples, labels, kfold = 3, pool = None):
    n = len(samples)
    folds = np.array_split(np.arange(n), kfold)
    def f(i):
        model = model_class(**params)
        test_idx = folds[i]
        train_idx = list(folds)
        train_idx.pop(i)
        train_idx = np.hstack(train_idx)
        train_samples, train_labels = samples[train_idx], labels[train_idx]
        test_samples, test_labels = samples[test_idx], labels[test_idx]
        model.train(train_samples, train_labels)
        resp = model.predict(test_samples)
        score = (resp != test_labels).mean()
        print ".",
        return score
    if pool is None:
        scores = map(f, xrange(kfold))
    else:
        scores = pool.map(f, xrange(kfold))
    return np.mean(scores)


class Detector(object):
    """Multi-scale object"""
    def __init__(self, model, feature):
        self.model = model
        self.feature = feature
        self.winSize = feature.winSize

    @staticmethod
    def overlap(rect1, rect2, size):
        start = min(rect1[0], rect2[0]), min(rect1[1], rect2[1])
        end = max(rect1[0], rect2[0])+size[0], max(rect1[1], rect2[1])+size[1]
        scale = 2*size[0] - (end[0]-start[0]), 2*size[1] - (end[1]-start[1])
        area = 0 if scale[0]<0 or scale[1]<0 else scale[0]*scale[1]
        return float(area)/(size[0]*size[1])
    @staticmethod
    def overlap_area(rect1, rect2):
        sx1,sy1,ex1,ey1 = rect1
        sx2,sy2,ex2,ey2 = rect2
        start = min(sx1, sx2), min(sy1, sy2)
        end = max(ex1, ex2), min(ey1, ey2)
        lap = (ex1-sx1) + (ex2-sx2) - (end[0]-start[0]), (ey1-sy1) + (ey2-sy2) - (end[1]-start[1])
        area = 0 if lap[0]<0 or lap[1]<0 else lap[0]*lap[1]
        small = min((ex1-sx1)*(ey1-sy1), (ex2-sx2)*(ey2-sy2))
        return float(area)/small
    @staticmethod
    def area(rect):
        return (rect[2]-rect[0])*(rect[3]-rect[1])
    @staticmethod
    def draw_rectangle(im, rects, color=(0,255,0),thickness=1):
        for rect in rects:
            cv2.rectangle(im, tuple(rect[:2]), tuple(rect[2:]), color=color, thickness=thickness)

    # @timer
    def detect(self, img, win_stride=(8,8), hit_threshold=0.6, debug=False):
        samples = []
        H, W = img.shape
        w, h = self.winSize
        assert W > w and H > h, 'detect window is too small'
        loc = []
        for y in xrange(0,H+1-h,win_stride[1]):
            for x in xrange(0,W+1-w,win_stride[0]):
                samples.append(img[y:y+h, x:x+w])
                loc.append((y,x))
                # fm = '%s\%04d.%s' % (r'temp\stack', num, 'png')
                # cv2.imwrite(fm, img[y:y+h, x:x+w])
        # print (H,W), len(samples)
        resp = self.model.predict(self.feature.process(samples))
        index = [i for i, v in enumerate(resp) if v==1]
        founds = np.int32(loc)[index]
        # for x,y in founds:
        #     # pad_w, pad_h = int(0.15*w), int(0.05*h)
        #     pad_w, pad_h = 0, 0
        #     cv2.rectangle(img, (x+pad_w, y+pad_h), (x+w-pad_w, y+h-pad_h), (0, 255, 0), 1)
        #     cv2.circle(img, (x,y), 1, (0,255,0), 2)
        #     cv2.waitKey()
        # center, radius = cv2.minEnclosingCircle(founds)

        if debug:
            dr = r'temp\stack'
            if os.path.isdir(dr):pass
            # __import__('shutil').rmtree(dr)
            else:
                os.makedirs(dr)
            for x,y in founds:
                # cv2.rectangle(img, (y, x), (y+w, x+h), (0, 255, 0), 1)
                cv2.imwrite(join(dr, '%sx%s.png' % (y,x)), img[x:x+h, y:y+w])
                # cv2.imshow(str(W), img)

        num = 1
        dct = {}
        # print founds
        for x,y in founds:
            # cv2.circle(img, (y,x), 1, (0,255,0), 2)
            if dct:
                flag = True
                for key in dct.keys():
                    v = dct[key]
                    rs = filter(lambda m: Detector.overlap((m[0],m[1]), (x,y), size=(h,w))<1-hit_threshold, v)
                    if not rs:
                        v.append([x,y])
                        dct[key] = v
                        flag = False
                        break
                if flag:
                    dct[num] = [[x,y]]
                    num += 1
            else:
                dct[num] = [[x,y]]
                num += 1
        fine = []
        for key in dct.keys():
            c, r = cv2.minEnclosingCircle(np.int32(dct[key]))
            c = int(c[0]+0.5), int(c[1]+0.5)
            fine.append(list(c))
        # center = int(center[0]), int(center[1])
        # cv2.circle(img, center, int(radius), (0,255,0), 1)
        return fine

    @timer
    def detectMultiScale(self, img, hit_threshold=0.6, win_stride=(8,8), scale=0.95, group_threshold=0.72, debug=False, fit=False, resize=(0.75, 0.85)):
        H, W = img.shape
        w, h = self.winSize
        t = max(float(h)/H, float(w)/W)
        # sequence = [scale**x for x in range(50) if scale**x >t]
        levels = int(np.log10(t)/np.log10(scale))+1
        # print levels
        sequence = [scale**x for x in range(levels)]

        # rule = (np.divide(np.float32([[w,h]]*len(sequence)), sequence)+0.5).astype(np.int32)
        locations = []

        # #muti-thread
        # ims = [cv2.resize(img, (int(s*W+0.5),int(s*H+0.5)), interpolation=cv2.INTER_CUBIC) for s in sequence]
        # # fines = [self.detect(im, win_stride=win_stride, hit_threshold=hit_threshold, debug=debug) for im in ims]
        # fines = multi_thread(self.detect, ims)
        # for fine in fines:
        #     if fine:
        #         # fine = np.int32(np.int32(fine)/s+0.5)
        #         tmp = []
        #         for x,y in fine:
        #             # cv2.rectangle(img, (int(y/s+0.5), int(x/s+0.5)), (int((y+w)/s+0.5), int((x+h)/s+0.5)), (0, 255, 0), 1)
        #             tmp.append([int(y/s+0.5),int(x/s+0.5),int((y+w)/s+0.5),int((x+h)/s+0.5)])
        #         locations.append(tmp)

        for s in sequence:
            im = cv2.resize(img, (int(s*W+0.5),int(s*H+0.5)), interpolation=cv2.INTER_CUBIC)
            fine = self.detect(im, win_stride=win_stride, hit_threshold=hit_threshold, debug=debug)
            if fine:
                # fine = np.int32(np.int32(fine)/s+0.5)
                tmp = []
                for x,y in fine:
                    # cv2.rectangle(img, (int(y/s+0.5), int(x/s+0.5)), (int((y+w)/s+0.5), int((x+h)/s+0.5)), (0, 255, 0), 1)
                    tmp.append([int(y/s+0.5),int(x/s+0.5),int((y+w)/s+0.5),int((x+h)/s+0.5)])
                locations.append(tmp)

        # print locations
        founds = []
        for group in locations:
            for rect in group:
                if founds:
                    flag = True
                    for i in range(len(founds)):
                        if Detector.overlap_area(rect,founds[i])>=group_threshold:
                            # founds[i] = (Detector.area(rect) > Detector.area(founds[i])) and rect or founds[i]
                            founds[i] = [(o+n)/2 for o,n in zip(rect,founds[i])]
                            flag = False
                            break
                    if flag:
                        founds.append(rect)
                else:
                    founds.append(rect)
        if fit and founds:
            for i in range(len(founds)):
                ix, iy, ax, ay = founds[i]
                delta_x = int((ax-ix)*(1-resize[0])/2+0.5)
                delta_y = int((ay-iy)*(1-resize[1])/2+0.5)
                founds[i] = [ix+delta_x, iy+delta_x, ax-delta_x, ay-delta_y]
        # Detector.draw_rectangle(img, founds)
        # cv2.imshow('dem', img)
        return founds